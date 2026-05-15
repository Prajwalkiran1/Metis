# MIGRATION_PLAN.md — Metis M2 Rework Schema Migration Plan

> Read this BEFORE running any migration. Each migration is independently testable and reversible.
> Migrations are additive-first; no destructive operations until the final constraint migration.

---

## OVERVIEW

The M2 rework extends the existing schema with 18 new tables, 4 enum extensions, and 1 critical column addition (USN). It does this across **three migrations**, each with a single concern:

| Migration | Concern | Risk | Reversible? |
|---|---|---|---|
| **0007** | Additive only — new tables, new enums, new nullable columns | Low | Yes (drop the new objects) |
| **0008** | Data backfill — populate USNs for existing seeded students, generate semester_setup records for existing offerings | Medium | Yes (truncate + restore from backup) |
| **0009** | Constraint tightening — make USN NOT NULL for students, add foreign key constraints, add CHECK constraints | Medium | Yes (drop constraints) |

**Golden rule**: never run migration N+1 without verifying migration N applied cleanly. Each migration ends with a verification SQL block.

---

## WHAT SURVIVES VERBATIM FROM M1–M4

These tables and their data are preserved without modification. The rework adds columns; it never drops or renames existing ones.

### From M1 (Users)
- `colleges` — preserved verbatim
- `users` — **GETS new columns**: `usn VARCHAR(20) NULL`, `dept_role_id UUID NULL` (HOD assignment)
- `roles` — preserved verbatim
- `permissions` — preserved verbatim
- `role_permissions` — preserved verbatim
- `auth_sessions` — preserved verbatim
- `user_invites` — preserved verbatim
- `password_reset_tokens` — preserved verbatim
- `consents` — preserved verbatim
- `audit_logs` — preserved verbatim
- `login_attempts` — preserved verbatim

### From M2 v1 (Academic)
- `departments` — preserved verbatim
- `academic_years` — preserved verbatim
- `academic_terms` — **GETS new column**: `term_type VARCHAR(20) DEFAULT 'regular'` (regular|fast_track schema-ready)
- `courses` — **GETS new column**: `course_type VARCHAR(20) DEFAULT 'theory'` (theory|lab|integrated|nptel)
- `sections` — preserved verbatim
- `batches` — preserved verbatim
- `rooms` — preserved verbatim
- `course_offerings` — **GETS new columns**: `parent_offering_id UUID NULL` (integrated theory↔lab link), `assessment_scheme_id UUID NULL` (FK to new table, nullable until configured)
- `timetable_slots` — preserved verbatim
- `timetable_exceptions` — preserved verbatim
- `academic_calendar` — preserved verbatim
- `enrollments` — **GETS new column**: `enrollment_state VARCHAR(20) DEFAULT 'active'` (active|dropped|withdrawn|migrated)

### From M3 (Attendance)
- `class_sessions` — preserved verbatim
- `attendance_qr_tokens` — preserved verbatim
- `attendance_records` — preserved verbatim (face stub keeps verification_confidence FLOAT)
- `attendance_overrides` — **DEPRECATED in favor of `academic_overrides`**; data migrated in 0008; old table dropped in 0009
- `attendance_eligibility_snapshots` — preserved verbatim (recomputed by new eligibility engine)

### From M4 (Marks)
- `assessments` — preserved verbatim
- `marks` — preserved verbatim
- `grade_rules` — **DEPRECATED in favor of `assessment_schemes` + `assessment_scheme_components`**; data migrated in 0008; old table dropped in 0009
- `guardian_links` — **GETS new column**: `created_via VARCHAR(20) DEFAULT 'admin_manual'` (admin_manual|csv_bulk|self_onboarding)
- `mark_edit_history` — preserved verbatim

---

## ENUM EXTENSIONS (Migration 0007)

PostgreSQL enums require `ALTER TYPE ADD VALUE`. Note: cannot be wrapped in a transaction with other DDL in some pg versions; we use separate transactions.

```sql
-- user_role enum: add 'hod'
ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'hod';

-- course_type enum: add 'nptel'  (theory, lab, integrated, nptel)
-- (If course_type was previously a VARCHAR with CHECK constraint, drop & re-add)
ALTER TYPE course_type ADD VALUE IF NOT EXISTS 'nptel';

-- term_type enum: NEW
CREATE TYPE term_type AS ENUM ('regular', 'fast_track');

-- enrollment_state enum: NEW
CREATE TYPE enrollment_state AS ENUM ('active', 'dropped', 'withdrawn', 'migrated');

-- semester_setup_state enum: NEW
CREATE TYPE semester_setup_state AS ENUM ('draft', 'published', 'active', 'archived');

-- assessment_component_kind enum: NEW
CREATE TYPE assessment_component_kind AS ENUM ('cie', 'aat', 'lab', 'assignment', 'see', 'nptel_assignment', 'nptel_final');

-- task_status enum: NEW
CREATE TYPE task_status AS ENUM ('pending', 'accepted', 'declined', 'completed', 'cancelled');

-- task_type enum: NEW
CREATE TYPE task_type AS ENUM ('invigilation', 'paper_setting', 'evaluation', 'makeup_exam', 'other');

-- override_type enum: NEW (typed academic overrides)
CREATE TYPE override_type AS ENUM (
  'attendance_condonation',
  'eligibility_override',
  'mark_lock_unlock',
  'student_migration',
  'lab_batch_reassignment',
  'assessment_scheme_unlock',
  'see_marks_correction',
  'makeup_cie_authorization'
);

-- grade_status enum: NEW
CREATE TYPE grade_status AS ENUM ('pending', 'released', 'i_incomplete', 'x_pending', 's', 'a', 'b', 'c', 'd', 'e', 'f', 'na');

-- see_result_kind enum: NEW
CREATE TYPE see_result_kind AS ENUM ('original', 're_evaluation', 'makeup');
```

---

## MIGRATION 0007 — ADDITIVE SCHEMA

**Concern**: Add all new tables and new nullable columns. Zero data changes. Zero constraints that could fail on existing data.

### New columns on existing tables

```sql
-- USN on users (nullable for now; constrained in 0009)
ALTER TABLE users ADD COLUMN IF NOT EXISTS usn VARCHAR(20) NULL;
CREATE INDEX IF NOT EXISTS idx_users_usn ON users(college_id, usn) WHERE usn IS NOT NULL;

-- HOD department-role assignment (one HOD per dept, but stored on user for flexibility)
ALTER TABLE users ADD COLUMN IF NOT EXISTS hod_of_department_id UUID NULL REFERENCES departments(id);
CREATE INDEX IF NOT EXISTS idx_users_hod_dept ON users(hod_of_department_id) WHERE hod_of_department_id IS NOT NULL;

-- term_type on academic_terms (schema-ready for fast track)
ALTER TABLE academic_terms ADD COLUMN IF NOT EXISTS term_type term_type DEFAULT 'regular' NOT NULL;

-- course_type on courses
-- (If course_type already exists as a column with text/varchar, this is a no-op; otherwise add)
ALTER TABLE courses ADD COLUMN IF NOT EXISTS course_type VARCHAR(20) DEFAULT 'theory' NOT NULL;

-- parent_offering_id on course_offerings (theory↔lab pairing for integrated courses)
ALTER TABLE course_offerings ADD COLUMN IF NOT EXISTS parent_offering_id UUID NULL REFERENCES course_offerings(id);
CREATE INDEX IF NOT EXISTS idx_offerings_parent ON course_offerings(parent_offering_id) WHERE parent_offering_id IS NOT NULL;

-- assessment_scheme_id on course_offerings (nullable until configured)
ALTER TABLE course_offerings ADD COLUMN IF NOT EXISTS assessment_scheme_id UUID NULL;

-- enrollment_state on enrollments
ALTER TABLE enrollments ADD COLUMN IF NOT EXISTS enrollment_state enrollment_state DEFAULT 'active' NOT NULL;

-- created_via on guardian_links (track CSV vs manual)
ALTER TABLE guardian_links ADD COLUMN IF NOT EXISTS created_via VARCHAR(20) DEFAULT 'admin_manual' NOT NULL;
```

### NEW TABLE: `semester_setups`

```sql
CREATE TABLE semester_setups (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  college_id UUID NOT NULL REFERENCES colleges(id),
  department_id UUID NOT NULL REFERENCES departments(id),
  academic_term_id UUID NOT NULL REFERENCES academic_terms(id),
  state semester_setup_state DEFAULT 'draft' NOT NULL,
  drafted_by_user_id UUID NOT NULL REFERENCES users(id),
  published_at TIMESTAMPTZ NULL,
  archived_at TIMESTAMPTZ NULL,
  notes TEXT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  deleted_at TIMESTAMPTZ NULL,
  UNIQUE (college_id, department_id, academic_term_id, deleted_at)
);
CREATE INDEX idx_semsetup_dept_term ON semester_setups(department_id, academic_term_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_semsetup_state ON semester_setups(state) WHERE deleted_at IS NULL;
```

### NEW TABLE: `elective_groups`

```sql
CREATE TABLE elective_groups (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  college_id UUID NOT NULL REFERENCES colleges(id),
  semester_setup_id UUID NOT NULL REFERENCES semester_setups(id),
  name VARCHAR(100) NOT NULL,
  description TEXT NULL,
  required_credits INTEGER NULL,
  min_enrollment_to_run INTEGER DEFAULT 5 NOT NULL,
  max_enrollment INTEGER NULL,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  deleted_at TIMESTAMPTZ NULL
);
CREATE INDEX idx_egroup_setup ON elective_groups(semester_setup_id) WHERE deleted_at IS NULL;
```

### NEW TABLE: `elective_group_options`

```sql
CREATE TABLE elective_group_options (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  college_id UUID NOT NULL REFERENCES colleges(id),
  elective_group_id UUID NOT NULL REFERENCES elective_groups(id),
  course_id UUID NOT NULL REFERENCES courses(id),
  tentative_teacher_id UUID NULL REFERENCES users(id),
  is_dissolved BOOLEAN DEFAULT false NOT NULL,
  dissolved_at TIMESTAMPTZ NULL,
  dissolved_by_user_id UUID NULL REFERENCES users(id),
  dissolved_reason TEXT NULL,
  migrated_to_option_id UUID NULL REFERENCES elective_group_options(id),
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  deleted_at TIMESTAMPTZ NULL
);
CREATE INDEX idx_eopt_group ON elective_group_options(elective_group_id) WHERE deleted_at IS NULL;
```

### NEW TABLE: `course_registrations`

```sql
CREATE TABLE course_registrations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  college_id UUID NOT NULL REFERENCES colleges(id),
  student_id UUID NOT NULL REFERENCES users(id),
  semester_setup_id UUID NOT NULL REFERENCES semester_setups(id),
  elective_group_id UUID NULL REFERENCES elective_groups(id),       -- NULL for mandatory courses
  elective_group_option_id UUID NULL REFERENCES elective_group_options(id),
  course_id UUID NOT NULL REFERENCES courses(id),
  status VARCHAR(20) DEFAULT 'approved' NOT NULL,                   -- pending, approved, migrated, cancelled, backlog
  is_backlog BOOLEAN DEFAULT false NOT NULL,
  backlog_source_term_id UUID NULL REFERENCES academic_terms(id),   -- if backlog, which term failed
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  deleted_at TIMESTAMPTZ NULL
);
CREATE INDEX idx_creg_student_setup ON course_registrations(student_id, semester_setup_id);
CREATE INDEX idx_creg_backlog ON course_registrations(student_id, is_backlog) WHERE is_backlog = true;
```

### NEW TABLE: `lab_batches`

```sql
CREATE TABLE lab_batches (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  college_id UUID NOT NULL REFERENCES colleges(id),
  course_offering_id UUID NOT NULL REFERENCES course_offerings(id),  -- the integrated/lab offering
  section_id UUID NOT NULL REFERENCES sections(id),
  name VARCHAR(50) NOT NULL,                                          -- "Batch A", "B1", "Batch 1"
  display_order INTEGER DEFAULT 1 NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  deleted_at TIMESTAMPTZ NULL,
  UNIQUE (course_offering_id, name, deleted_at)
);
CREATE INDEX idx_labbatch_offering ON lab_batches(course_offering_id) WHERE deleted_at IS NULL;
```

### NEW TABLE: `lab_batch_members`

```sql
CREATE TABLE lab_batch_members (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  college_id UUID NOT NULL REFERENCES colleges(id),
  lab_batch_id UUID NOT NULL REFERENCES lab_batches(id),
  student_id UUID NOT NULL REFERENCES users(id),
  added_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  removed_at TIMESTAMPTZ NULL,
  removed_reason TEXT NULL,
  UNIQUE (lab_batch_id, student_id, removed_at)
);
CREATE INDEX idx_labbatch_member_student ON lab_batch_members(student_id) WHERE removed_at IS NULL;
```

### NEW TABLE: `lab_batch_assignments` (batch incharges)

```sql
CREATE TABLE lab_batch_assignments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  college_id UUID NOT NULL REFERENCES colleges(id),
  lab_batch_id UUID NOT NULL REFERENCES lab_batches(id),
  teacher_id UUID NOT NULL REFERENCES users(id),
  role VARCHAR(30) DEFAULT 'batch_incharge' NOT NULL,    -- batch_incharge | co_evaluator
  assigned_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  unassigned_at TIMESTAMPTZ NULL,
  unassigned_reason TEXT NULL,
  UNIQUE (lab_batch_id, teacher_id, role, unassigned_at)
);
CREATE INDEX idx_labbatch_assign_teacher ON lab_batch_assignments(teacher_id) WHERE unassigned_at IS NULL;
```

### NEW TABLE: `assessment_scheme_templates`

```sql
CREATE TABLE assessment_scheme_templates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  college_id UUID NOT NULL REFERENCES colleges(id),
  owner_department_id UUID NULL REFERENCES departments(id),  -- NULL = institutional template
  name VARCHAR(100) NOT NULL,                                -- "Theory Standard", "Integrated Standard", "NPTEL Standard"
  description TEXT NULL,
  applies_to_course_type VARCHAR(20) NOT NULL,               -- theory|lab|integrated|nptel
  validation_rules JSONB NOT NULL DEFAULT '{}'::jsonb,       -- { "cie_count": 3, "cie_best_of": 2, "cie_equal_weights": true, "aat_max_percent": 40, "see_rescale_to": 50 }
  default_components JSONB NOT NULL DEFAULT '[]'::jsonb,     -- [{ kind: "cie", count: 3, max_each: 40, weight: 0.4 }, ...]
  is_active BOOLEAN DEFAULT true NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  deleted_at TIMESTAMPTZ NULL
);
CREATE INDEX idx_scheme_tpl_dept ON assessment_scheme_templates(owner_department_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_scheme_tpl_type ON assessment_scheme_templates(applies_to_course_type) WHERE deleted_at IS NULL;
```

### NEW TABLE: `assessment_schemes` (per-offering instance)

```sql
CREATE TABLE assessment_schemes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  college_id UUID NOT NULL REFERENCES colleges(id),
  course_offering_id UUID NOT NULL REFERENCES course_offerings(id) UNIQUE,
  template_id UUID NULL REFERENCES assessment_scheme_templates(id),  -- nullable for fully custom
  configured_by_user_id UUID NOT NULL REFERENCES users(id),
  is_locked BOOLEAN DEFAULT false NOT NULL,
  locked_at TIMESTAMPTZ NULL,
  locked_reason TEXT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  deleted_at TIMESTAMPTZ NULL
);
```

### NEW TABLE: `assessment_scheme_components`

```sql
CREATE TABLE assessment_scheme_components (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  college_id UUID NOT NULL REFERENCES colleges(id),
  assessment_scheme_id UUID NOT NULL REFERENCES assessment_schemes(id),
  kind assessment_component_kind NOT NULL,
  label VARCHAR(50) NOT NULL,                       -- "CIE-1", "CIE-2", "CIE-3", "AAT", "Lab", "Assignment-AAT", "Final"
  max_marks NUMERIC(6,2) NOT NULL,
  weight_percent NUMERIC(5,2) NOT NULL,             -- 0–100
  ordinal INTEGER DEFAULT 1 NOT NULL,
  is_dropped_in_best_of BOOLEAN DEFAULT false NOT NULL,
  metadata JSONB DEFAULT '{}'::jsonb NOT NULL,      -- per-component config: "best_of_group" for CIE, "linked_assignment_ids", etc.
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  deleted_at TIMESTAMPTZ NULL,
  UNIQUE (assessment_scheme_id, label, deleted_at)
);
CREATE INDEX idx_scheme_comp_scheme ON assessment_scheme_components(assessment_scheme_id) WHERE deleted_at IS NULL;
```

### NEW TABLE: `nptel_enrollments`

```sql
CREATE TABLE nptel_enrollments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  college_id UUID NOT NULL REFERENCES colleges(id),
  course_offering_id UUID NOT NULL REFERENCES course_offerings(id),  -- the NPTEL slot offering
  student_id UUID NOT NULL REFERENCES users(id),
  specific_nptel_course_name VARCHAR(200) NOT NULL,                   -- "Deep Learning - IIT Madras"
  specific_nptel_course_url TEXT NULL,
  certificate_url TEXT NULL,                                          -- R2 URL for uploaded certificate
  certificate_verified BOOLEAN DEFAULT false NOT NULL,
  certificate_verified_by UUID NULL REFERENCES users(id),
  certificate_verified_at TIMESTAMPTZ NULL,
  completion_status VARCHAR(20) DEFAULT 'in_progress' NOT NULL,       -- in_progress | completed | carried_over | passed | failed
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  deleted_at TIMESTAMPTZ NULL,
  UNIQUE (course_offering_id, student_id, deleted_at)
);
CREATE INDEX idx_nptel_student ON nptel_enrollments(student_id, completion_status) WHERE deleted_at IS NULL;
```

### NEW TABLE: `internal_deadlines`

```sql
CREATE TABLE internal_deadlines (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  college_id UUID NOT NULL REFERENCES colleges(id),
  academic_term_id UUID NOT NULL REFERENCES academic_terms(id),
  department_id UUID NULL REFERENCES departments(id),       -- NULL = institutional hard stop
  course_offering_id UUID NULL REFERENCES course_offerings(id),  -- NULL = applies to dept or institution
  deadline_at TIMESTAMPTZ NOT NULL,
  kind VARCHAR(20) NOT NULL,                                -- institutional_hard | department_soft | per_course_freeze
  set_by_user_id UUID NOT NULL REFERENCES users(id),
  is_frozen BOOLEAN DEFAULT false NOT NULL,                 -- once frozen, requires HOD/admin to unfreeze
  frozen_at TIMESTAMPTZ NULL,
  frozen_by_user_id UUID NULL REFERENCES users(id),
  notes TEXT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  deleted_at TIMESTAMPTZ NULL
);
CREATE INDEX idx_intdl_term ON internal_deadlines(academic_term_id, kind) WHERE deleted_at IS NULL;
CREATE INDEX idx_intdl_offering ON internal_deadlines(course_offering_id) WHERE course_offering_id IS NOT NULL AND deleted_at IS NULL;
```

### NEW TABLE: `cie_schedule`

```sql
CREATE TABLE cie_schedule (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  college_id UUID NOT NULL REFERENCES colleges(id),
  course_offering_id UUID NOT NULL REFERENCES course_offerings(id),
  cie_number INTEGER NOT NULL,                          -- 1, 2, 3
  scheduled_at TIMESTAMPTZ NOT NULL,
  duration_minutes INTEGER DEFAULT 60 NOT NULL,
  room_id UUID NULL REFERENCES rooms(id),
  notes TEXT NULL,
  is_published BOOLEAN DEFAULT false NOT NULL,
  published_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  deleted_at TIMESTAMPTZ NULL,
  UNIQUE (course_offering_id, cie_number, deleted_at)
);
CREATE INDEX idx_cie_offering ON cie_schedule(course_offering_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_cie_published ON cie_schedule(is_published, scheduled_at) WHERE deleted_at IS NULL;
```

### NEW TABLE: `tasks`

```sql
CREATE TABLE tasks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  college_id UUID NOT NULL REFERENCES colleges(id),
  assigned_by_user_id UUID NOT NULL REFERENCES users(id),
  assigned_to_user_id UUID NOT NULL REFERENCES users(id),
  task_type task_type NOT NULL,
  title VARCHAR(200) NOT NULL,
  description TEXT NULL,
  related_entity_type VARCHAR(50) NULL,         -- 'cie_schedule', 'course_offering', etc.
  related_entity_id UUID NULL,
  due_at TIMESTAMPTZ NULL,
  status task_status DEFAULT 'pending' NOT NULL,
  status_updated_at TIMESTAMPTZ NULL,
  decline_reason TEXT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  deleted_at TIMESTAMPTZ NULL
);
CREATE INDEX idx_tasks_assignee ON tasks(assigned_to_user_id, status) WHERE deleted_at IS NULL;
CREATE INDEX idx_tasks_assigner ON tasks(assigned_by_user_id) WHERE deleted_at IS NULL;
```

### NEW TABLE: `hall_tickets`

```sql
CREATE TABLE hall_tickets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  college_id UUID NOT NULL REFERENCES colleges(id),
  student_id UUID NOT NULL REFERENCES users(id),
  academic_term_id UUID NOT NULL REFERENCES academic_terms(id),
  generated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  approved_at TIMESTAMPTZ NULL,
  approved_by_user_id UUID NULL REFERENCES users(id),
  current_version_id UUID NULL,                  -- FK to hall_ticket_versions, latest
  is_active BOOLEAN DEFAULT true NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  deleted_at TIMESTAMPTZ NULL,
  UNIQUE (student_id, academic_term_id, deleted_at)
);
CREATE INDEX idx_ht_term ON hall_tickets(academic_term_id) WHERE deleted_at IS NULL;
```

### NEW TABLE: `hall_ticket_versions`

```sql
CREATE TABLE hall_ticket_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  college_id UUID NOT NULL REFERENCES colleges(id),
  hall_ticket_id UUID NOT NULL REFERENCES hall_tickets(id),
  version_number INTEGER NOT NULL,
  pdf_url TEXT NOT NULL,                          -- R2 URL
  eligibility_snapshot JSONB NOT NULL,            -- frozen per-subject eligibility at gen time
  generated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  generated_by_user_id UUID NOT NULL REFERENCES users(id),
  UNIQUE (hall_ticket_id, version_number)
);
CREATE INDEX idx_htv_ticket ON hall_ticket_versions(hall_ticket_id, version_number DESC);
```

### NEW TABLE: `grade_cards`

```sql
CREATE TABLE grade_cards (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  college_id UUID NOT NULL REFERENCES colleges(id),
  student_id UUID NOT NULL REFERENCES users(id),
  academic_term_id UUID NOT NULL REFERENCES academic_terms(id),
  current_version_id UUID NULL,                   -- FK to grade_card_versions, latest
  is_finalised BOOLEAN DEFAULT false NOT NULL,    -- true after all SEE released for this term
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  deleted_at TIMESTAMPTZ NULL,
  UNIQUE (student_id, academic_term_id, deleted_at)
);
CREATE INDEX idx_gc_student ON grade_cards(student_id) WHERE deleted_at IS NULL;
```

### NEW TABLE: `grade_card_versions`

```sql
CREATE TABLE grade_card_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  college_id UUID NOT NULL REFERENCES colleges(id),
  grade_card_id UUID NOT NULL REFERENCES grade_cards(id),
  version_number INTEGER NOT NULL,
  pdf_url TEXT NOT NULL,                          -- R2 URL
  grades_snapshot JSONB NOT NULL,                 -- frozen grades at gen time per course
  generated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  generated_by_user_id UUID NOT NULL REFERENCES users(id),
  trigger_reason VARCHAR(50) NOT NULL,            -- initial | see_released | re_eval | makeup_completed
  UNIQUE (grade_card_id, version_number)
);
CREATE INDEX idx_gcv_card ON grade_card_versions(grade_card_id, version_number DESC);
```

### NEW TABLE: `see_results`

```sql
CREATE TABLE see_results (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  college_id UUID NOT NULL REFERENCES colleges(id),
  enrollment_id UUID NOT NULL REFERENCES enrollments(id),
  kind see_result_kind NOT NULL,                  -- original | re_evaluation | makeup
  marks_obtained NUMERIC(6,2) NULL,               -- NULL = pending; max from scheme
  max_marks NUMERIC(6,2) NOT NULL,
  uploaded_at TIMESTAMPTZ NULL,
  uploaded_by_user_id UUID NULL REFERENCES users(id),
  csv_upload_batch_id UUID NULL,                  -- correlate CSV uploads
  notes TEXT NULL,
  superseded_by UUID NULL REFERENCES see_results(id),  -- chain: original → re_eval → makeup
  is_current BOOLEAN DEFAULT true NOT NULL,       -- only one is_current per enrollment
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  deleted_at TIMESTAMPTZ NULL
);
CREATE INDEX idx_see_enroll ON see_results(enrollment_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_see_current ON see_results(enrollment_id, is_current) WHERE is_current = true AND deleted_at IS NULL;
```

### NEW TABLE: `re_evaluations`

```sql
CREATE TABLE re_evaluations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  college_id UUID NOT NULL REFERENCES colleges(id),
  enrollment_id UUID NOT NULL REFERENCES enrollments(id),
  requested_by_student_id UUID NOT NULL REFERENCES users(id),
  request_window_id UUID NULL,                    -- correlate windowed batches
  requested_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  status VARCHAR(20) DEFAULT 'requested' NOT NULL, -- requested | processing | completed | rejected
  original_see_result_id UUID NOT NULL REFERENCES see_results(id),
  revised_see_result_id UUID NULL REFERENCES see_results(id),
  outcome VARCHAR(20) NULL,                       -- improved | held | rejected
  reason TEXT NULL,
  resolved_at TIMESTAMPTZ NULL,
  resolved_by_user_id UUID NULL REFERENCES users(id),
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  deleted_at TIMESTAMPTZ NULL
);
CREATE INDEX idx_reeval_student ON re_evaluations(requested_by_student_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_reeval_status ON re_evaluations(status) WHERE deleted_at IS NULL;
```

### NEW TABLE: `academic_overrides` (typed semantic actions)

```sql
CREATE TABLE academic_overrides (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  college_id UUID NOT NULL REFERENCES colleges(id),
  override_type override_type NOT NULL,
  actor_user_id UUID NOT NULL REFERENCES users(id),
  target_student_id UUID NULL REFERENCES users(id),
  target_course_offering_id UUID NULL REFERENCES course_offerings(id),
  target_entity_type VARCHAR(50) NULL,
  target_entity_id UUID NULL,
  old_value JSONB NULL,
  new_value JSONB NULL,
  reason TEXT NOT NULL,
  evidence_url TEXT NULL,
  approved_by_user_id UUID NULL REFERENCES users(id),
  approved_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);
CREATE INDEX idx_acovr_student ON academic_overrides(target_student_id) WHERE target_student_id IS NOT NULL;
CREATE INDEX idx_acovr_actor ON academic_overrides(actor_user_id);
CREATE INDEX idx_acovr_type ON academic_overrides(override_type);
```

### NEW TABLE: `eligibility_snapshots` (replaces v1 attendance_eligibility_snapshots in spirit)

```sql
CREATE TABLE eligibility_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  college_id UUID NOT NULL REFERENCES colleges(id),
  student_id UUID NOT NULL REFERENCES users(id),
  course_offering_id UUID NOT NULL REFERENCES course_offerings(id),
  as_of_at TIMESTAMPTZ NOT NULL,
  attendance_percent NUMERIC(5,2) NOT NULL,
  cie_eligibility JSONB NOT NULL,                 -- { "cie_1": true, "cie_2": false, "cie_3": null }
  see_eligible BOOLEAN NOT NULL,
  makeup_see_eligible BOOLEAN NOT NULL,
  internal_marks_percent NUMERIC(5,2) NULL,
  internal_threshold_met BOOLEAN NULL,            -- 40% rule for main, 60% for makeup
  condonation_applied_percent NUMERIC(5,2) DEFAULT 0 NOT NULL,
  is_finalised BOOLEAN DEFAULT false NOT NULL,    -- true post-internal-deadline
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);
CREATE INDEX idx_eligsnap_student_offering ON eligibility_snapshots(student_id, course_offering_id, as_of_at DESC);
CREATE INDEX idx_eligsnap_finalised ON eligibility_snapshots(is_finalised, as_of_at DESC) WHERE is_finalised = true;
```

### NEW TABLE: `course_drops` (schema-ready, deferred UI)

```sql
CREATE TABLE course_drops (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  college_id UUID NOT NULL REFERENCES colleges(id),
  enrollment_id UUID NOT NULL REFERENCES enrollments(id),
  kind VARCHAR(20) NOT NULL,                      -- 'drop' (no grade) | 'withdraw' (W grade)
  reason TEXT NULL,
  initiated_by_user_id UUID NOT NULL REFERENCES users(id),
  approved_by_user_id UUID NULL REFERENCES users(id),
  effective_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);
CREATE INDEX idx_cdrop_enroll ON course_drops(enrollment_id);
```

### Add `parent_visible` flags to existing tables (additive)

```sql
-- Marks publication events get parent visibility flag
-- (the marks-publish event itself, not individual marks rows — too granular)
ALTER TABLE marks ADD COLUMN IF NOT EXISTS parent_visible BOOLEAN DEFAULT true NOT NULL;
-- Note: per-post toggle for ANNOUNCEMENTS lives in M5 schema (when M5 ships)
-- For ASSIGNMENTS, the flag is on the assignment row itself (M11 schema)
```

### Verification block — run after migration 0007

```sql
-- Verify all new tables exist
SELECT table_name FROM information_schema.tables
  WHERE table_schema = 'public'
  AND table_name IN (
    'semester_setups', 'elective_groups', 'elective_group_options',
    'course_registrations', 'lab_batches', 'lab_batch_members',
    'lab_batch_assignments', 'assessment_scheme_templates',
    'assessment_schemes', 'assessment_scheme_components',
    'nptel_enrollments', 'internal_deadlines', 'cie_schedule',
    'tasks', 'hall_tickets', 'hall_ticket_versions',
    'grade_cards', 'grade_card_versions', 'see_results',
    're_evaluations', 'academic_overrides', 'eligibility_snapshots',
    'course_drops'
  )
ORDER BY table_name;
-- Expected: 23 rows

-- Verify enum extensions
SELECT enumlabel FROM pg_enum WHERE enumtypid = 'user_role'::regtype ORDER BY enumlabel;
-- Expected: includes 'hod'

SELECT typname FROM pg_type WHERE typname IN (
  'term_type','enrollment_state','semester_setup_state',
  'assessment_component_kind','task_status','task_type',
  'override_type','grade_status','see_result_kind'
);
-- Expected: 9 rows

-- Verify new columns
SELECT column_name FROM information_schema.columns
  WHERE table_name = 'users' AND column_name IN ('usn','hod_of_department_id');
-- Expected: 2 rows

-- No data has been touched — existing M1/M2/M3/M4 data should be unchanged
SELECT COUNT(*) FROM users;       -- should match pre-migration count
SELECT COUNT(*) FROM enrollments; -- should match pre-migration count
```

### Rollback for 0007 (if anything fails)

```sql
-- Drop new tables in reverse dependency order
DROP TABLE IF EXISTS course_drops CASCADE;
DROP TABLE IF EXISTS eligibility_snapshots CASCADE;
DROP TABLE IF EXISTS academic_overrides CASCADE;
DROP TABLE IF EXISTS re_evaluations CASCADE;
DROP TABLE IF EXISTS see_results CASCADE;
DROP TABLE IF EXISTS grade_card_versions CASCADE;
DROP TABLE IF EXISTS grade_cards CASCADE;
DROP TABLE IF EXISTS hall_ticket_versions CASCADE;
DROP TABLE IF EXISTS hall_tickets CASCADE;
DROP TABLE IF EXISTS tasks CASCADE;
DROP TABLE IF EXISTS cie_schedule CASCADE;
DROP TABLE IF EXISTS internal_deadlines CASCADE;
DROP TABLE IF EXISTS nptel_enrollments CASCADE;
DROP TABLE IF EXISTS assessment_scheme_components CASCADE;
DROP TABLE IF EXISTS assessment_schemes CASCADE;
DROP TABLE IF EXISTS assessment_scheme_templates CASCADE;
DROP TABLE IF EXISTS lab_batch_assignments CASCADE;
DROP TABLE IF EXISTS lab_batch_members CASCADE;
DROP TABLE IF EXISTS lab_batches CASCADE;
DROP TABLE IF EXISTS course_registrations CASCADE;
DROP TABLE IF EXISTS elective_group_options CASCADE;
DROP TABLE IF EXISTS elective_groups CASCADE;
DROP TABLE IF EXISTS semester_setups CASCADE;

-- Drop new columns from existing tables
ALTER TABLE users DROP COLUMN IF EXISTS usn;
ALTER TABLE users DROP COLUMN IF EXISTS hod_of_department_id;
ALTER TABLE academic_terms DROP COLUMN IF EXISTS term_type;
ALTER TABLE courses DROP COLUMN IF EXISTS course_type;
ALTER TABLE course_offerings DROP COLUMN IF EXISTS parent_offering_id;
ALTER TABLE course_offerings DROP COLUMN IF EXISTS assessment_scheme_id;
ALTER TABLE enrollments DROP COLUMN IF EXISTS enrollment_state;
ALTER TABLE guardian_links DROP COLUMN IF EXISTS created_via;
ALTER TABLE marks DROP COLUMN IF EXISTS parent_visible;

-- Drop new enums (only after columns referencing them are dropped)
DROP TYPE IF EXISTS see_result_kind CASCADE;
DROP TYPE IF EXISTS grade_status CASCADE;
DROP TYPE IF EXISTS override_type CASCADE;
DROP TYPE IF EXISTS task_type CASCADE;
DROP TYPE IF EXISTS task_status CASCADE;
DROP TYPE IF EXISTS assessment_component_kind CASCADE;
DROP TYPE IF EXISTS semester_setup_state CASCADE;
DROP TYPE IF EXISTS enrollment_state CASCADE;
DROP TYPE IF EXISTS term_type CASCADE;
-- Note: 'hod' value cannot be removed from user_role enum without recreating the type
-- (PostgreSQL limitation). If rollback truly needed, dump + recreate enum.
```

---

## MIGRATION 0008 — DATA BACKFILL

**Concern**: Populate USNs for existing seeded students. Generate semester_setup records from existing offerings. Migrate any v1 attendance_overrides to typed academic_overrides. Migrate any v1 grade_rules to assessment_schemes.

```sql
-- 1. Backfill USN for existing seeded students using a deterministic pattern
-- BMSCE format: 1BM + YY + DD + RRR
-- For seeded students, derive YY from enrollment year (or default 23 if unknown),
-- DD from department code mapping, RRR from a sequence within (year, dept)

DO $$
DECLARE
  rec RECORD;
  seq_num INTEGER;
BEGIN
  FOR rec IN
    SELECT u.id, u.email, u.created_at, d.code AS dept_code
    FROM users u
    LEFT JOIN departments d ON d.id = (
      SELECT department_id FROM enrollments WHERE student_id = u.id ORDER BY created_at LIMIT 1
    )
    WHERE u.role = 'student'
      AND u.usn IS NULL
      AND u.deleted_at IS NULL
    ORDER BY u.created_at
  LOOP
    SELECT COALESCE(MAX(CAST(SUBSTRING(usn FROM 8 FOR 3) AS INTEGER)), 0) + 1
      INTO seq_num
      FROM users
      WHERE usn LIKE '1BM' || TO_CHAR(rec.created_at, 'YY') || COALESCE(rec.dept_code, 'XX') || '%';

    UPDATE users
      SET usn = '1BM' || TO_CHAR(rec.created_at, 'YY')
              || COALESCE(rec.dept_code, 'XX')
              || LPAD(seq_num::TEXT, 3, '0')
      WHERE id = rec.id;
  END LOOP;
END $$;

-- Verify backfill
SELECT COUNT(*) AS students_total,
       COUNT(*) FILTER (WHERE usn IS NOT NULL) AS students_with_usn,
       COUNT(*) FILTER (WHERE usn IS NULL) AS students_missing_usn
FROM users
WHERE role = 'student' AND deleted_at IS NULL;
-- Expected: students_missing_usn = 0


-- 2. Generate semester_setup records for existing course_offerings
-- Each unique (department, academic_term) combination → one semester_setup
-- These start in 'active' state (already running)
INSERT INTO semester_setups (
  college_id, department_id, academic_term_id, state,
  drafted_by_user_id, published_at
)
SELECT DISTINCT
  co.college_id,
  c.department_id,
  co.academic_term_id,
  'active',
  (SELECT id FROM users WHERE role = 'admin' AND college_id = co.college_id LIMIT 1),
  NOW()
FROM course_offerings co
JOIN courses c ON c.id = co.course_id
WHERE co.deleted_at IS NULL
  AND c.deleted_at IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM semester_setups ss
    WHERE ss.department_id = c.department_id
      AND ss.academic_term_id = co.academic_term_id
      AND ss.deleted_at IS NULL
  );


-- 3. Migrate v1 attendance_overrides (if any rows exist) to typed academic_overrides
INSERT INTO academic_overrides (
  college_id, override_type, actor_user_id,
  target_student_id, target_course_offering_id,
  target_entity_type, target_entity_id,
  reason, created_at
)
SELECT
  ao.college_id,
  'attendance_condonation',
  ao.overridden_by_user_id,
  ao.student_id,
  cs.course_offering_id,
  'attendance_record',
  ao.attendance_record_id,
  COALESCE(ao.reason, 'Migrated from v1 attendance_overrides'),
  ao.created_at
FROM attendance_overrides ao
JOIN attendance_records ar ON ar.id = ao.attendance_record_id
JOIN class_sessions cs ON cs.id = ar.class_session_id
WHERE NOT EXISTS (
  SELECT 1 FROM academic_overrides ao2
  WHERE ao2.target_entity_id = ao.attendance_record_id
    AND ao2.override_type = 'attendance_condonation'
);


-- 4. Migrate v1 grade_rules to assessment_schemes + assessment_scheme_components
-- (Each grade_rule row becomes one assessment_scheme with components)
DO $$
DECLARE
  gr RECORD;
  scheme_id UUID;
BEGIN
  FOR gr IN
    SELECT gr.id AS rule_id, gr.course_offering_id, gr.college_id,
           gr.cie_weight, gr.see_weight, gr.assignment_weight, gr.lab_weight, gr.aat_weight,
           gr.created_by_user_id
    FROM grade_rules gr
    WHERE gr.deleted_at IS NULL
  LOOP
    INSERT INTO assessment_schemes (
      college_id, course_offering_id, template_id, configured_by_user_id, is_locked
    ) VALUES (
      gr.college_id, gr.course_offering_id, NULL, gr.created_by_user_id, false
    )
    RETURNING id INTO scheme_id;

    -- Components (only insert those with non-zero weight)
    IF gr.cie_weight > 0 THEN
      INSERT INTO assessment_scheme_components (college_id, assessment_scheme_id, kind, label, max_marks, weight_percent, ordinal)
        VALUES (gr.college_id, scheme_id, 'cie', 'CIE', 40, gr.cie_weight, 1);
    END IF;
    IF gr.see_weight > 0 THEN
      INSERT INTO assessment_scheme_components (college_id, assessment_scheme_id, kind, label, max_marks, weight_percent, ordinal)
        VALUES (gr.college_id, scheme_id, 'see', 'SEE', 100, gr.see_weight, 4);
    END IF;
    IF gr.assignment_weight > 0 THEN
      INSERT INTO assessment_scheme_components (college_id, assessment_scheme_id, kind, label, max_marks, weight_percent, ordinal)
        VALUES (gr.college_id, scheme_id, 'assignment', 'Assignment', 10, gr.assignment_weight, 2);
    END IF;
    IF gr.lab_weight > 0 THEN
      INSERT INTO assessment_scheme_components (college_id, assessment_scheme_id, kind, label, max_marks, weight_percent, ordinal)
        VALUES (gr.college_id, scheme_id, 'lab', 'Lab', 25, gr.lab_weight, 3);
    END IF;
    IF gr.aat_weight > 0 THEN
      INSERT INTO assessment_scheme_components (college_id, assessment_scheme_id, kind, label, max_marks, weight_percent, ordinal)
        VALUES (gr.college_id, scheme_id, 'aat', 'AAT', 10, gr.aat_weight, 5);
    END IF;

    -- Link back from course_offerings
    UPDATE course_offerings SET assessment_scheme_id = scheme_id WHERE id = gr.course_offering_id;
  END LOOP;
END $$;


-- 5. Seed institutional assessment_scheme_templates (BMSCE defaults)
INSERT INTO assessment_scheme_templates (
  college_id, owner_department_id, name, description, applies_to_course_type,
  validation_rules, default_components, is_active
)
SELECT
  c.id, NULL, 'Theory Standard', 'BMSCE default for theory courses', 'theory',
  '{"cie_count": 3, "cie_best_of": 2, "cie_equal_weights": true, "aat_max_percent": 40, "see_rescale_to": 50, "internal_threshold_main_percent": 40, "internal_threshold_makeup_percent": 60}'::jsonb,
  '[
    {"kind":"cie","label":"CIE-1","max_marks":40,"weight_percent":20,"ordinal":1,"metadata":{"best_of_group":"cie"}},
    {"kind":"cie","label":"CIE-2","max_marks":40,"weight_percent":20,"ordinal":2,"metadata":{"best_of_group":"cie"}},
    {"kind":"cie","label":"CIE-3","max_marks":40,"weight_percent":20,"ordinal":3,"metadata":{"best_of_group":"cie"}},
    {"kind":"aat","label":"AAT","max_marks":20,"weight_percent":10,"ordinal":4},
    {"kind":"see","label":"SEE","max_marks":100,"weight_percent":50,"ordinal":5}
  ]'::jsonb,
  true
FROM colleges c
WHERE NOT EXISTS (
  SELECT 1 FROM assessment_scheme_templates t
  WHERE t.college_id = c.id AND t.name = 'Theory Standard' AND t.owner_department_id IS NULL
);

INSERT INTO assessment_scheme_templates (
  college_id, owner_department_id, name, description, applies_to_course_type,
  validation_rules, default_components, is_active
)
SELECT
  c.id, NULL, 'Integrated Standard', 'BMSCE default for integrated (theory + lab) courses', 'integrated',
  '{"cie_count": 3, "cie_best_of": 2, "cie_equal_weights": true, "lab_required": true, "see_rescale_to": 50, "internal_threshold_main_percent": 40, "internal_threshold_makeup_percent": 60}'::jsonb,
  '[
    {"kind":"cie","label":"CIE-1","max_marks":20,"weight_percent":10,"ordinal":1,"metadata":{"best_of_group":"cie"}},
    {"kind":"cie","label":"CIE-2","max_marks":20,"weight_percent":10,"ordinal":2,"metadata":{"best_of_group":"cie"}},
    {"kind":"cie","label":"CIE-3","max_marks":20,"weight_percent":10,"ordinal":3,"metadata":{"best_of_group":"cie"}},
    {"kind":"lab","label":"Lab","max_marks":25,"weight_percent":25,"ordinal":4},
    {"kind":"aat","label":"AAT","max_marks":5,"weight_percent":5,"ordinal":5},
    {"kind":"see","label":"SEE","max_marks":100,"weight_percent":50,"ordinal":6}
  ]'::jsonb,
  true
FROM colleges c
WHERE NOT EXISTS (
  SELECT 1 FROM assessment_scheme_templates t
  WHERE t.college_id = c.id AND t.name = 'Integrated Standard' AND t.owner_department_id IS NULL
);

INSERT INTO assessment_scheme_templates (
  college_id, owner_department_id, name, description, applies_to_course_type,
  validation_rules, default_components, is_active
)
SELECT
  c.id, NULL, 'NPTEL Standard', 'BMSCE default for NPTEL/MOOC courses', 'nptel',
  '{"no_attendance": true, "no_cie": true, "carry_over_allowed": true}'::jsonb,
  '[
    {"kind":"nptel_assignment","label":"NPTEL Assignments","max_marks":40,"weight_percent":40,"ordinal":1},
    {"kind":"nptel_final","label":"NPTEL Final Exam","max_marks":60,"weight_percent":60,"ordinal":2}
  ]'::jsonb,
  true
FROM colleges c
WHERE NOT EXISTS (
  SELECT 1 FROM assessment_scheme_templates t
  WHERE t.college_id = c.id AND t.name = 'NPTEL Standard' AND t.owner_department_id IS NULL
);
```

### Verification block — run after migration 0008

```sql
-- All students have USNs
SELECT COUNT(*) FILTER (WHERE usn IS NULL) AS missing
FROM users WHERE role = 'student' AND deleted_at IS NULL;
-- Expected: 0

-- USNs match pattern
SELECT COUNT(*) FROM users
WHERE role = 'student'
  AND usn IS NOT NULL
  AND usn !~ '^1BM\d{2}[A-Z]{2}\d{3}$';
-- Expected: 0 (all match pattern)

-- USNs are unique per college
SELECT college_id, usn, COUNT(*) AS cnt
FROM users WHERE usn IS NOT NULL
GROUP BY college_id, usn HAVING COUNT(*) > 1;
-- Expected: empty result

-- Every active course_offering has an assessment_scheme
SELECT COUNT(*) FROM course_offerings
WHERE deleted_at IS NULL AND assessment_scheme_id IS NULL;
-- Expected: 0 (all offerings linked)

-- Institutional templates exist
SELECT COUNT(*) FROM assessment_scheme_templates
WHERE owner_department_id IS NULL AND is_active = true;
-- Expected: 3 per college (Theory Standard, Integrated Standard, NPTEL Standard)

-- semester_setups generated
SELECT COUNT(*) FROM semester_setups;
-- Expected: at least one per (dept, term) that had offerings
```

### Rollback for 0008

```sql
-- Reverse the assessment_scheme link
UPDATE course_offerings SET assessment_scheme_id = NULL;
DELETE FROM assessment_scheme_components;
DELETE FROM assessment_schemes;

-- Remove migrated overrides (only the migrated ones)
DELETE FROM academic_overrides
  WHERE reason = 'Migrated from v1 attendance_overrides';

-- Remove generated semester_setups (only the migration-generated ones, identified by their drafted_by being an admin and state='active' with no draft history)
-- Be careful here — if you've already created real setups, this will hit them too
DELETE FROM semester_setups
  WHERE state = 'active' AND published_at IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM academic_overrides WHERE target_entity_id = semester_setups.id);

-- Remove backfilled USNs
UPDATE users SET usn = NULL WHERE role = 'student';

-- Remove seeded templates
DELETE FROM assessment_scheme_templates WHERE owner_department_id IS NULL;
```

---

## MIGRATION 0009 — CONSTRAINT TIGHTENING

**Concern**: Make USN NOT NULL for students. Add CHECK constraints. Add foreign key on `course_offerings.assessment_scheme_id`. Drop deprecated tables.

```sql
-- 1. NOT NULL on USN for students (after backfill)
ALTER TABLE users ADD CONSTRAINT users_student_usn_required
  CHECK (role != 'student' OR usn IS NOT NULL OR deleted_at IS NOT NULL);

-- 2. USN format CHECK (BMSCE pattern; relax-able via config flag later)
ALTER TABLE users ADD CONSTRAINT users_usn_format
  CHECK (usn IS NULL OR usn ~ '^1BM\d{2}[A-Z]{2}\d{3}$');

-- 3. UNIQUE USN per college
ALTER TABLE users ADD CONSTRAINT users_usn_unique_per_college
  EXCLUDE (college_id WITH =, usn WITH =) WHERE (usn IS NOT NULL AND deleted_at IS NULL);

-- 4. FK on course_offerings.assessment_scheme_id (now that backfill is done)
ALTER TABLE course_offerings
  ADD CONSTRAINT fk_offerings_scheme
  FOREIGN KEY (assessment_scheme_id) REFERENCES assessment_schemes(id);

-- 5. ENUM CHECK on courses.course_type (if it was VARCHAR with a CHECK before)
ALTER TABLE courses DROP CONSTRAINT IF EXISTS courses_course_type_check;
ALTER TABLE courses ADD CONSTRAINT courses_course_type_check
  CHECK (course_type IN ('theory', 'lab', 'integrated', 'nptel'));

-- 6. Hall ticket pointer constraint
ALTER TABLE hall_tickets
  ADD CONSTRAINT fk_ht_current_version
  FOREIGN KEY (current_version_id) REFERENCES hall_ticket_versions(id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE grade_cards
  ADD CONSTRAINT fk_gc_current_version
  FOREIGN KEY (current_version_id) REFERENCES grade_card_versions(id) DEFERRABLE INITIALLY DEFERRED;

-- 7. SEE result: only one current per enrollment
CREATE UNIQUE INDEX uq_see_one_current_per_enrollment
  ON see_results(enrollment_id)
  WHERE is_current = true AND deleted_at IS NULL;

-- 8. AAT weight CHECK (BMSCE rule: <= 40%)
ALTER TABLE assessment_scheme_components
  ADD CONSTRAINT aat_max_40pct
  CHECK (kind != 'aat' OR weight_percent <= 40);

-- 9. Drop deprecated v1 tables (NOW safely, since data migrated)
-- Comment these out if you want to keep v1 tables for rollback safety
-- DROP TABLE IF EXISTS attendance_overrides CASCADE;
-- DROP TABLE IF EXISTS grade_rules CASCADE;

-- 10. HOD role: at most one active HOD per department
CREATE UNIQUE INDEX uq_one_hod_per_dept
  ON users(hod_of_department_id)
  WHERE hod_of_department_id IS NOT NULL AND deleted_at IS NULL;
```

### Verification block — run after migration 0009

```sql
-- All students have USNs (NOT NULL enforced)
SELECT COUNT(*) FROM users
WHERE role = 'student' AND usn IS NULL AND deleted_at IS NULL;
-- Expected: 0

-- USN uniqueness holds
SELECT college_id, usn, COUNT(*) FROM users WHERE usn IS NOT NULL GROUP BY 1, 2 HAVING COUNT(*) > 1;
-- Expected: empty

-- One HOD per department
SELECT hod_of_department_id, COUNT(*) FROM users
WHERE hod_of_department_id IS NOT NULL AND deleted_at IS NULL
GROUP BY hod_of_department_id HAVING COUNT(*) > 1;
-- Expected: empty
```

### Rollback for 0009

```sql
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_student_usn_required;
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_usn_format;
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_usn_unique_per_college;
ALTER TABLE course_offerings DROP CONSTRAINT IF EXISTS fk_offerings_scheme;
ALTER TABLE courses DROP CONSTRAINT IF EXISTS courses_course_type_check;
ALTER TABLE hall_tickets DROP CONSTRAINT IF EXISTS fk_ht_current_version;
ALTER TABLE grade_cards DROP CONSTRAINT IF EXISTS fk_gc_current_version;
DROP INDEX IF EXISTS uq_see_one_current_per_enrollment;
ALTER TABLE assessment_scheme_components DROP CONSTRAINT IF EXISTS aat_max_40pct;
DROP INDEX IF EXISTS uq_one_hod_per_dept;
```

---

## EXECUTION ORDER (RECOMMENDED)

```bash
# 1. Backup DB first
pg_dump $DATABASE_URL > metis_pre_rework_$(date +%Y%m%d_%H%M%S).sql

# 2. Run 0007 (additive)
alembic upgrade +1   # or specific revision

# 3. Run verification block for 0007 manually
psql $DATABASE_URL -f scripts/verify_0007.sql

# 4. Run 0008 (data backfill)
alembic upgrade +1

# 5. Run verification for 0008
psql $DATABASE_URL -f scripts/verify_0008.sql

# 6. Manual spot-check: open psql, check 10 random students have plausible USNs

# 7. Run 0009 (constraints)
alembic upgrade +1

# 8. Run verification for 0009
psql $DATABASE_URL -f scripts/verify_0009.sql

# 9. Smoke-test the API: hit /admin/users — confirm USN column appears, M1 endpoints unbroken
```

If anything fails at any step, run the rollback for that migration and investigate before proceeding.

---

## WHAT GETS DROPPED (only after data migrated, only in 0009 or later)

These v1 tables are functionally replaced. Leave commented-out drops in 0009; run them in a future migration once you're certain no code references them:

- `attendance_overrides` → replaced by `academic_overrides` with `override_type = 'attendance_condonation'`
- `grade_rules` → replaced by `assessment_schemes` + `assessment_scheme_components`

When ready to drop:
```sql
DROP TABLE attendance_overrides CASCADE;
DROP TABLE grade_rules CASCADE;
```

---

## FUTURE SCHEMA NOTES (NOT THIS REWORK)

These tables exist as schema-ready stubs for later modules; not populated in M2 rework:

- **`course_drops`** — drop/withdraw functionality lives here when UI is built (post-MVP)
- **`academic_terms.term_type = 'fast_track'`** — fast-track semester support is schema-ready; UI in a future module
- **Assignment tables (M11)** — assignments, assignment_submissions, assignment_grades — added in M11 session
- **Content tables (M6)** — materials, material_versions, material_views — added in M6
- **Communication tables (M5)** — announcements, messages, notifications, notification_preferences — added in M5

---

*Migration plan v1.0 — three additive-first migrations, each independently testable and reversible. Run sequentially with verification between steps.*

---

## POST-AUDIT REWORK ADDITIONS (Sessions 3 + 4)

The audit-rework cycle (AUDIT_FINDINGS.md) shipped two additional migrations on
top of the M2-rework baseline. Both are additive, independently reversible, and
verified against the seeded BMSCE corpus.

### Migration 0013 — `task_assignments` (audit Session 3)

**Concern**: Split the M10d `tasks` row into a header + N per-assignee rows so
real workflows (paper-setting committees, multi-invigilator CIEs) can be
modelled. Audit finding B15.

```sql
CREATE TABLE task_assignments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  assignee_user_id UUID NOT NULL REFERENCES users(id),
  status task_status NOT NULL DEFAULT 'pending',
  status_updated_at TIMESTAMPTZ NULL,
  decline_reason TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at TIMESTAMPTZ NULL
);
CREATE INDEX ix_task_assignments_task_id ON task_assignments(task_id);
CREATE INDEX ix_task_assignments_assignee_user_id ON task_assignments(assignee_user_id);
CREATE UNIQUE INDEX uq_task_assignments_task_assignee_active
  ON task_assignments(task_id, assignee_user_id)
  WHERE deleted_at IS NULL;
```

Backfill (one assignment row per existing task), then drop the per-assignee
columns from `tasks` in the same migration:

```sql
INSERT INTO task_assignments (id, task_id, assignee_user_id, status, status_updated_at, decline_reason, created_at, updated_at, deleted_at)
SELECT gen_random_uuid(), id, assigned_to_user_id, status, status_updated_at, decline_reason, created_at, updated_at, deleted_at
FROM tasks WHERE deleted_at IS NULL;

ALTER TABLE tasks DROP COLUMN assigned_to_user_id;
ALTER TABLE tasks DROP COLUMN status;
ALTER TABLE tasks DROP COLUMN status_updated_at;
ALTER TABLE tasks DROP COLUMN decline_reason;
```

Verify: `services/api/alembic/verify/verify_0013.sql`.

### Migration 0014 — `course_registration_preferences` (audit Session 4)

**Concern**: Add ranked elective preferences (1st / 2nd / 3rd choice per
student per elective group) to drive the auto-fallback cascade on
dissolution. Audit findings B6 + B7. `course_registrations` stays untouched
as the committed-enrolment table; this new table is pure intent.

```sql
CREATE TABLE course_registration_preferences (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  college_id UUID NOT NULL REFERENCES colleges(id),
  semester_setup_id UUID NOT NULL REFERENCES semester_setups(id),
  student_user_id UUID NOT NULL REFERENCES users(id),
  elective_group_id UUID NOT NULL REFERENCES elective_groups(id),
  elective_group_option_id UUID NOT NULL REFERENCES elective_group_options(id),
  preference_rank SMALLINT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at TIMESTAMPTZ NULL,
  CHECK (preference_rank BETWEEN 1 AND 3)
);
CREATE INDEX ix_crp_student_setup
  ON course_registration_preferences (student_user_id, semester_setup_id);
CREATE INDEX ix_crp_option
  ON course_registration_preferences (elective_group_option_id);
CREATE UNIQUE INDEX uq_crp_student_group_rank_active
  ON course_registration_preferences
     (student_user_id, semester_setup_id, elective_group_id, preference_rank)
  WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_crp_student_group_option_active
  ON course_registration_preferences
     (student_user_id, semester_setup_id, elective_group_id, elective_group_option_id)
  WHERE deleted_at IS NULL;
```

Backfill — every existing approved elective registration becomes a rank-1
preference (migrated / cancelled / backlog rows are historical audit and
intentionally not backfilled):

```sql
INSERT INTO course_registration_preferences (
  id, college_id, semester_setup_id, student_user_id,
  elective_group_id, elective_group_option_id,
  preference_rank, created_at, updated_at, deleted_at
)
SELECT gen_random_uuid(), cr.college_id, cr.semester_setup_id, cr.student_user_id,
       cr.elective_group_id, cr.elective_group_option_id,
       1, cr.created_at, cr.updated_at, NULL
FROM course_registrations cr
WHERE cr.elective_group_id IS NOT NULL
  AND cr.elective_group_option_id IS NOT NULL
  AND cr.status = 'approved'
  AND cr.deleted_at IS NULL;
```

Also adds the `'needs_intervention'` status string convention on
`course_registrations.status` (no schema change — column is already
VARCHAR(20)). New rows with this status carry `elective_group_option_id =
NULL` and `course_id` reusing the dissolved option's course_id as a display
placeholder.

Verify: `services/api/alembic/verify/verify_0014.sql`.

---

*Audit additions: migrations 0013 and 0014. The audit rework plan lives in
`AUDIT_FINDINGS.md` at repo root; the cycle is closed as of 2026-05-15.*
