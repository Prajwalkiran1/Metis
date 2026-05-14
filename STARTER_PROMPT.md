# STARTER_PROMPT.md — Next Claude Code Session Kickoff

> Copy the prompt below verbatim into your Claude Code CLI session.
> It's tuned for the **M2 Rework** session — schema additions, USN backfill, HOD role, empty HOD shell.
> Pre-conditions: you've already pulled latest from `deepthi-sm/Metis`, replaced `CLAUDE.md`, and added the three new docs (this file plus `MIGRATION_PLAN.md` and `AI_DEFERRAL_PLAN.md`) to the repo root.

---

## THE PROMPT (paste this into Claude Code)

```
I am starting the M2 REWORK session for the Metis project.

CONTEXT:
- I have replaced CLAUDE.md with the new v2.0 version. Read it first.
- I have added three new reference documents at the repo root:
  - CLAUDE.md (the new project intelligence file)
  - MIGRATION_PLAN.md (three-migration plan: 0007 additive, 0008 backfill, 0009 constraints)
  - AI_DEFERRAL_PLAN.md (AI layer is deferred; stubs and scaffolds ship now)
- The old file CLAUDE-v1-archive.md is kept for git history reference only — do not treat as authoritative.

WHAT THIS SESSION DOES (M2 REWORK):
1. Apply migration 0007 (additive schema): 18 new tables, 9 new enums, ~9 new nullable columns on existing tables.
2. Apply migration 0008 (data backfill): generate USNs for existing students using BMSCE pattern, generate semester_setups from existing offerings, migrate v1 attendance_overrides → academic_overrides, migrate v1 grade_rules → assessment_schemes + components, seed 3 institutional assessment scheme templates.
3. Apply migration 0009 (constraints): NOT NULL on USN for students, USN format CHECK, USN uniqueness per college, FK on course_offerings.assessment_scheme_id, AAT weight ≤40% CHECK, one HOD per dept constraint.
4. Add the `hod` role to all RBAC enums, scopes, and middleware. HOD inherits teacher scope + adds department-scope privileges.
5. Light backend updates (no full M10 module yet — that's the next session). Just enough for the new schema to be queryable and the new role to authenticate.
6. Frontend deltas (frontend-as-we-go is non-negotiable):
   - /admin/users — add USN column with filter
   - /admin/academic — Course form gets `course_type` selector including NPTEL
   - /hod/* — NEW empty shell with auth guard for the `hod` role + /hod/dashboard placeholder ("M10 will populate this")
7. Update CLAUDE.md ACTIVE MODULE STATE block at the end of the session.

WHAT THIS SESSION DOES NOT DO:
- Do NOT build any M10 workflow logic (semester setup CRUD, elective management, lab batch composer, scheme picker, CIE scheduling, hall tickets, grade cards, SEE upload, makeup, re-eval, tasks). All of that is M10 a-e in subsequent sessions.
- Do NOT build M11 (assignments), M5 (comms), M6 (content), M9 (admin reports).
- Do NOT touch M3 attendance or M4 marks rework — they are blocked by M10 (event bus).
- Do NOT implement face verification beyond the existing stub. M8 swaps it later.
- Do NOT build any AI service code beyond the scaffold (if scaffolds don't yet exist, create them per AI_DEFERRAL_PLAN.md scaffold minimum).

GIT/COMMIT RULES (NON-NEGOTIABLE):
- Verify git identity before any commit:
    git config user.name
    git config user.email
  Both should be MY name and email, not "Claude" or "anthropic".
- DO NOT include "Co-Authored-By: Claude" or any Claude attribution in commit messages.
- DO NOT add "Generated with Claude Code" footers.
- Conventional commits format only:
    feat(scope): subject
    fix(scope): subject
    chore(schema): subject
    docs(adr): subject
- I will be pushing to two remotes (origin = my repo, upstream = teammate's repo). When pushing, both must remain trace-free of AI attribution.

WORKING DIRECTORY:
- Work strictly inside ~/Metis. Do not create files outside this directory.

SESSION CONTRACT (from CLAUDE.md):
- Brainstorm before code — ask me at least 3 clarifying questions before writing the first migration file.
- Schema first → migrations applied → models → endpoints (light) → UI deltas.
- Every endpoint touched gets its UI updated this session — no "frontend later."
- shadcn-style primitives (apps/web/components/ui.tsx) only. No custom palettes.
- react-hook-form + zod for any new forms.
- Each migration runs cleanly with its verification block before moving to the next.
- End the session with: (1) all migrations applied + verified, (2) tests passing, (3) updated ACTIVE MODULE STATE yaml block to paste into CLAUDE.md.

START BY:
1. Reading CLAUDE.md fully.
2. Reading MIGRATION_PLAN.md fully.
3. Reading AI_DEFERRAL_PLAN.md fully (so you understand what the scaffold files should contain).
4. Reading the existing M1, M2, M3, M4 module code and prior progress notes to understand current state.
5. Asking me at least 3 clarifying questions about the rework before writing any code.
6. Proposing the order of operations for the session (e.g., "I'll do migration 0007 first, verify, then 0008, verify, then 0009, then RBAC for HOD, then UI deltas").

Do not start coding until I confirm the plan.
```

---

## WHAT TO PASTE AFTER CLAUDE ASKS QUESTIONS

When Claude asks clarifying questions (it will — that's the session contract), here are likely topics and prepared answers so you can respond quickly:

### "Should I create the scaffold services for learning-engine and insights-engine in this session, or defer them?"
**Answer**: Create them now. Per AI_DEFERRAL_PLAN.md, the scaffold minimum is two empty FastAPI apps with `/health` endpoints. Build them now so deployment topology is correct from day one.

### "How should USNs be assigned during the backfill — fully deterministic, or with manual review?"
**Answer**: Fully deterministic per MIGRATION_PLAN.md migration 0008. Use the BMSCE pattern `1BM + YY + DD + RRR`. Year from student creation timestamp, dept code from primary enrollment's department, sequence number within (year, dept). If a student has no enrollments (rare seed-data edge case), use `XX` as dept code and flag for manual review in the verification step.

### "What happens to the existing M1 admin user(s) — do they get a USN too?"
**Answer**: No. USN is only for students (`role = 'student'`). The CHECK constraint in migration 0009 is `role != 'student' OR usn IS NOT NULL`. Admins, teachers, HODs, parents → `usn` stays NULL.

### "Should I add the `hod_of_department_id` to the existing seeded admin user as a way to test HOD role, or create a new HOD user via seed data?"
**Answer**: Create a new HOD user via seed data — assign them to the CSE department (or whichever first department exists in the seed). Don't repurpose the admin user; their role stays admin. The new HOD user lets us test cross-role behavior (admin views vs HOD views).

### "How should the `/hod/*` shell handle a user who is HOD of one department but trying to view another department?"
**Answer**: 403 Forbidden. HOD scope is strictly their own department. The middleware should check `current_user.hod_of_department_id == requested_department_id` for any department-scoped HOD endpoint. Same applies to the frontend route guard.

### "Should the empty HOD dashboard show a 'coming soon' message, or some real data (like the user's teaching load if HOD also teaches)?"
**Answer**: Show real data where it exists. The HOD dashboard placeholder should:
- Show "Welcome, HOD of {department}" header
- Show their own teaching offerings if any (links to /teacher/courses/{id})
- Show a section "Department overview" with "M10 module will populate this" placeholder
- This way the page is functional even before M10 ships.

### "Should the assessment scheme templates be seeded only for the institutional level (`owner_department_id = NULL`), or also pre-seed some department-specific examples?"
**Answer**: Only institutional templates in migration 0008 (3 templates: Theory Standard, Integrated Standard, NPTEL Standard). Department-specific templates are created by HODs in M10c (assessment scheme + lab batches session). Don't pre-seed those.

### "Should the migration of `grade_rules` → `assessment_schemes` happen for ALL grade_rules rows, even soft-deleted ones?"
**Answer**: Only non-soft-deleted rows (`WHERE deleted_at IS NULL`). Per migration 0008's DO block. Soft-deleted v1 grade_rules stay where they are; the new schema is what's used going forward.

### "If a student is already enrolled in a course offering with no assessment_scheme yet linked, what should the UI show under /student/courses/{id} marks tab?"
**Answer**: After migration 0008, every course_offering should have an assessment_scheme (the migration auto-links them). If somehow one is missing post-backfill, the marks tab should show "Assessment scheme not yet configured — contact your instructor." This is an edge case the verification step in 0008 should catch (the SQL query `SELECT COUNT(*) FROM course_offerings WHERE deleted_at IS NULL AND assessment_scheme_id IS NULL` should return 0).

### "Are there any existing v1 endpoints I should mark deprecated this session, or do they stay until M4 rework?"
**Answer**: They stay. Don't deprecate M1/M2/M3/M4 v1 endpoints in this session. The M2 rework is purely additive — old endpoints work, new schema is queryable, no consumer is forced off the old shape yet. M4 rework session is where mark-related endpoints get refactored to use schemes; M3 rework is where attendance gets the eligibility engine; both come after this rework lands cleanly.

### "Should I run the migrations against a fresh database or against the existing one with data?"
**Answer**: Against the existing one with data — that's the whole point of the backfill migration 0008. Make sure to `pg_dump` first (the playbook covers this). If you're testing locally, use your local Postgres which should already have the M1/M2/M3/M4 seed data. If something goes wrong, restore from the dump and try again.

---

## TIPS FOR DRIVING THE SESSION

**1. Don't let Claude skip the brainstorm.** If Claude starts writing migration files immediately, stop it: "First answer my questions and propose the order of operations." The brainstorm protects against half the bugs.

**2. Verify each migration's verification block before moving on.** When Claude says "migration 0007 applied," ask: "Run the verification SQL block from MIGRATION_PLAN.md section 0007. Paste the results." Don't proceed to 0008 without seeing the green ticks.

**3. Watch for `Co-Authored-By` slipping into commits.** After every `git commit`, run:
```
git log -1 --format='%an %ae'
git log -1 --format='%B'
```
The first should be YOUR name. The second should NOT contain "Claude" anywhere.

**4. If Claude starts building M10 features in this session, redirect.** The line: "That's M10. This session is M2 rework only. Stop and just finish the schema + HOD shell."

**5. Keep the session focused on the contract.** End-of-session checklist:
- [ ] All 3 migrations applied + verified
- [ ] HOD role added to enums, scopes, middleware
- [ ] /admin/users shows USN column
- [ ] /admin/academic Course form has NPTEL option
- [ ] /hod/* route exists, /hod/dashboard renders with real auth
- [ ] At least one HOD user created via seed
- [ ] Tests passing (existing M1–M4 tests should still pass; if any break, fix before commit)
- [ ] Git commits authored as you, no Claude attribution
- [ ] ACTIVE MODULE STATE block updated and pasted into CLAUDE.md

**6. If something goes wrong, rollback per MIGRATION_PLAN.md.** Don't try to "fix forward" in the same session if a migration fails partway. Roll back, investigate, fix the migration file, restart from `pg_dump` backup.

**7. End the session cleanly.** Ask Claude: "Generate the updated ACTIVE MODULE STATE yaml block to paste into CLAUDE.md." Paste it in, commit, push.

---

## NEXT SESSIONS AFTER M2 REWORK

In order:

1. **M2 Rework** (this session) ← you are here
2. **M10a — Semester Setup + HOD Approval Flow**
3. **M10b — Elective Registration + Dissolution + Cascade**
4. **M10c — Lab Batches + Assessment Scheme Picker**
5. **M10d — CIE Schedule + Tasks + Internal Deadlines + Event Bus**
6. **M10e — Hall Tickets + Grade Cards + SEE/Re-eval/Makeup**
7. **M3 Rework — Eligibility Engine + Freeze Integration**
8. **M4 Rework — Scheme Integration + NPTEL + Grade Card Generation**
9. **M11 — Assignments**
10. **M5 — Communications**
11. **M6 — Content**
12. **M9 — Admin Portal + Analytics**
13. **Polish + Deploy**
14. **M7 — Learning Engine** (AI)
15. **M8 — Insights + Face Verify** (AI)

Each session is its own conversation with its own starter prompt (similar format). Don't try to do more than one in a session.

---

## EMERGENCY PROMPTS

**If Claude goes off-track**:
> Stop. You're outside the scope of this session. Re-read CLAUDE.md → BUILD SEQUENCE and confirm we're on M2 rework, then narrow back to schema + HOD shell.

**If Claude tries to skip the frontend**:
> The session contract requires frontend-as-we-go. Every endpoint we touch needs its UI updated this session. List the UI deltas you still owe me.

**If Claude writes a commit with Claude attribution**:
> That commit has Claude attribution. Amend it with: `git commit --amend --no-edit --reset-author`. Verify with `git log -1 --format='%an %ae %B'`.

**If a migration fails**:
> Stop. Run the rollback block from MIGRATION_PLAN.md for migration {N}. Then investigate the failure. Don't try to fix forward.

**If you want to end the session**:
> Generate the updated ACTIVE MODULE STATE yaml block for CLAUDE.md. List everything we shipped this session. List anything we deferred to the next session. Then stop.

---

*Starter prompt v1.0 — paste the prompt block at the top, hold the line on the contract, end with state-block update.*
