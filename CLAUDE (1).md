# CLAUDE.md — Metis Project Intelligence File
> Single source of truth for Claude Code sessions. Paste this file at the start of every session.
> Update the MODULE STATUS TABLE and ACTIVE MODULE STATE after every session.

---

## HOW TO USE THIS FILE

1. **Starting a session**: Tell Claude which module you're working on and paste this file. Claude will read the module status, pick up where you left off, and begin with a brainstorm/refinement phase before writing code.
2. **Session contract**: Every session ends with a skeleton that is *runnable* — routes registered, UI screens navigable, no broken imports — even if features are stubs.
3. **Ending a session**: Ask Claude to "update the module state block" and paste the output back into this file before closing.
4. **Brainstorm mode**: Say "let's brainstorm [module]" and Claude will ask clarifying questions before writing a single line of code.
5. **Never skip the skeleton rule**: If a session ends early, the module must at minimum have its router/page registered and returning a 200/placeholder.

---

## PROJECT SNAPSHOT

```
PROJECT: Metis — AI-Native University Operating System
TARGET:  BMS College of Engineering, Bangalore (scales to all Indian engineering colleges)
BUILDER: Final-year CS (Data Science) student | Strong in ML/AI/data pipelines
TIMELINE: 8-week MVP
BUDGET:  Zero — free tiers only. Every infra decision must run free.
COMPLIANCE: DPDP Act 2023 — face biometric data never persisted to disk.
CODE STANDARD: Production-grade. Every file must be explainable in a technical interview.
```

---

## WHAT METIS IS

- Role-based web platform: **Student / Teacher / Admin**
- **Smart Attendance**: QR + GPS + face verification, anti-proxy
- **AI Learning Engine**: RAG tutor per student, knowledge graph, personalised paths
- **AI Insights Engine**: Proactive teacher alerts, risk detection, intervention support
- **Communication**: Announcements, direct messages, notification system
- **Marks & Assessment**: CIE/SEE entry, grade computation, performance history
- **Content Management**: Material uploads → auto-ingested into AI knowledge base

## WHAT METIS IS NOT
- Generic ERP or SAP clone
- Basic CRUD portal
- Prototype — everything is written to be deployable and defensible

---

## FRONTEND PHILOSOPHY — MVP PHASE

```
CURRENT PHASE: Bare-bones functional UI. Every screen and feature works. Zero design polish.
FUTURE PHASE:  Visual redesign using Claude Design / Figma / other tools AFTER all features are verified.

Rules Claude must follow for ALL frontend work in this phase:

UI RULES (non-negotiable during MVP):
  ✅ Every feature and data point from the screen inventory MUST be present and functional
  ✅ Use shadcn/ui base components only — no custom styling beyond what shadcn provides
  ✅ Layout: simple top nav + sidebar + content area. No creative layouts.
  ✅ No custom color palettes, gradients, animations, or decorative elements
  ✅ No pixel-tweaking or spacing obsession — default Tailwind spacing is fine
  ✅ Tables for tabular data, forms for input, cards for grouped info — pick the obvious element
  ✅ Every button must do something (even if it calls a stub endpoint)
  ✅ Every form must validate and submit (even if backend returns mock data)
  ✅ Loading states: simple spinner or "Loading..." text — nothing fancy
  ✅ Error states: plain red text message — nothing fancy
  ✅ Mobile responsive enough to not break — not optimised

UI NON-GOALS (explicitly deferred to redesign phase):
  ❌ Do NOT spend time on colour schemes or brand identity
  ❌ Do NOT build custom components when shadcn has one
  ❌ Do NOT add hover effects, transitions, or micro-interactions
  ❌ Do NOT try to match any design mockup or visual reference
  ❌ Do NOT refactor working UI to look better — move to next feature instead

COMPONENT STRATEGY:
  - shadcn/ui: Button, Input, Select, Table, Card, Dialog, Tabs, Badge, Form, Toast
  - Data display: use <Table> — do not build custom list views
  - Navigation: use a plain sidebar with links — do not build a custom nav system
  - Charts: recharts with default styles — no custom theming
  - Icons: lucide-react defaults

HANDOFF CONTRACT (what gets handed to redesign tools later):
  - All pages exist with correct data flowing through them
  - All API calls wired to real endpoints
  - Component boundaries are clean (easy to restyle without logic changes)
  - No styling logic mixed into data-fetching or business logic
  - Components accept data as props — styles are purely in className strings (easy to swap)
```

---

## ARCHITECTURE — 6 LAYERS

```
L1  CLIENT      Student PWA | Teacher PWA | Admin Web | Mobile Attendance App
                → Next.js 14 App Router. /student /teacher /admin sub-apps.

L2  GATEWAY     API Gateway (rate limit, routing) | WebSocket Server | Auth Service
                → Single entry point. Auth validated here before forwarding.

L3  CORE SVCS   M1 User | M2 Academic | M3 Attendance | M4 Marks |
                M5 Comms | M6 Content | M9 Analytics
                → FastAPI modular routers. REST internally, Redis pub/sub for async.

L4  AI LAYER    M7 Learning Engine | M8 Insights + Face Verify | LLM Orchestrator
                → Separate Python services. Isolated for independent redeployment.

L5  DATA        PostgreSQL (Supabase) | Qdrant (vectors) | NetworkX→Neo4j (graph) |
                Redis (cache/queue) | Cloudflare R2 (files)

L6  INFRA       Vercel (frontend) | Render (backend) | Railway (AI services) |
                Sentry (errors) | Grafana Cloud (metrics)
```

---

## TECH STACK

| Layer | Technology | Why | Free Tier |
|---|---|---|---|
| Backend framework | FastAPI (Python) | Async, OpenAPI autodocs, Pydantic, same language as ML | Yes |
| Frontend | Next.js 14 App Router | RSC, file routing, PWA via next-pwa, trivial Vercel deploy | Yes |
| Styling | Tailwind CSS + shadcn/ui | Utility-first, zero runtime — **bare bones MVP phase only** | Yes |
| Primary DB | PostgreSQL (Supabase) | Relational integrity, RLS, 500MB free | Yes |
| Vector DB | Qdrant (self-hosted Render) | Rust-based, fast, better filtering than Chroma | Yes |
| Cache + Queue | Redis (Upstash) | Serverless, 10K cmd/day free, QR TTL + pub/sub + BullMQ | Yes |
| File storage | Cloudflare R2 | S3-compatible, free egress, 10GB free | Yes |
| Embeddings | sentence-transformers (MiniLM-L6-v2) | Local, zero API cost, 384-dim | Always free |
| Face verify | DeepFace (FaceNet backbone) | Open source, CPU-capable, state-of-art | Always free |
| LLM primary | Gemini 1.5 Flash | 1M tokens/day free, 1M context, multimodal | Yes |
| LLM fallback 1 | Groq (Llama 3 8B) | 6000 RPM free, fast inference | Yes |
| LLM fallback 2 | Ollama (local) | Dev/test only, Phi-3 or Gemma 2B | Always free |
| Auth | JWT (15min) + refresh (7d) | Stateless, works across services | — |
| Jobs | BullMQ (Redis-backed) | Background pipeline jobs | — |

---

## EVENT BUS — INTER-MODULE COMMUNICATION

```
Sync:   REST via internal API calls (request/response flows)
Async:  Redis pub/sub (non-blocking, no module imports another's models)

Event                  Publisher    Subscribers
─────────────────────────────────────────────────────────────────────
attendance.marked      M3           M8 (update risk), M9 (analytics)
marks.updated          M4           M8 (re-rank alerts), M9 (analytics)
material.uploaded      M6           M7 (start ingestion)
user.enrolled          M1           M2 (add to batch), M7 (init graph)
insight.generated      M8           M5 (trigger teacher notification)
session.created        M2           M3 (open QR window)
ingestion.complete     M7           M9 (analytics)
notification.queued    M5           (delivery workers)
```

---

## DATA LAYER RULES (apply to every module)

```
Multi-tenancy:  Every table has college_id. Query ALWAYS includes WHERE college_id = ?
Soft deletes:   deleted_at TIMESTAMP NULL on all tables. Filter WHERE deleted_at IS NULL.
Audit trail:    Sensitive writes → insert row in audit_logs (actor_id, action, old_val, new_val, ts)
Timestamps:     created_at TIMESTAMPTZ DEFAULT NOW(), updated_at auto-trigger
Face data:      NEVER stored. Only verification_confidence FLOAT in attendance_records.
Naming:         snake_case everywhere. Foreign keys: {table_singular}_id.
```

---

## REPO STRUCTURE

```
metis/
├── apps/
│   ├── web/                    # Next.js 14 frontend
│   │   ├── app/
│   │   │   ├── (student)/      # Student sub-app
│   │   │   ├── (teacher)/      # Teacher sub-app
│   │   │   └── (admin)/        # Admin sub-app
│   │   └── components/
│   └── mobile/                 # PWA attendance client
├── services/
│   ├── api/                    # FastAPI main backend
│   │   ├── modules/
│   │   │   ├── users/          # M1
│   │   │   ├── academic/       # M2
│   │   │   ├── attendance/     # M3
│   │   │   ├── marks/          # M4
│   │   │   ├── comms/          # M5
│   │   │   ├── content/        # M6
│   │   │   └── admin/          # M9
│   │   └── core/               # shared DB, auth, config, event bus
│   ├── learning-engine/        # M7 Python AI service
│   └── insights-engine/        # M8 Python AI service
├── infra/
│   ├── docker/
│   └── scripts/                # migrations, seed data
├── docs/
│   ├── adr/                    # Architecture Decision Records
│   └── diagrams/
└── tests/
    ├── unit/
    ├── integration/
    └── e2e/
```

---

## MODULE STATUS TABLE
> Update this table at the end of every session.

| Module | Status | Skeleton Live? | Features Done | Blocked By |
|---|---|---|---|---|
| M1 User Service | 🔴 Not started | No | — | — |
| M2 Academic Service | 🔴 Not started | No | — | M1 |
| M3 Attendance Service | 🔴 Not started | No | — | M1, M2, M8 |
| M4 Marks Service | 🔴 Not started | No | — | M1, M2 |
| M5 Comms Service | 🔴 Not started | No | — | M1, M2 |
| M6 Content Service | 🔴 Not started | No | — | M1, M2, M7 |
| M7 Learning Engine | 🔴 Not started | No | — | M6 |
| M8 Insights + Face | 🔴 Not started | No | — | M3, M4 |
| M9 Admin + Analytics | 🔴 Not started | No | — | All |

**Status legend**: 🔴 Not started · 🟡 Skeleton live · 🟠 In progress · 🟢 Complete · ⚫ Blocked

---

## MODULE DEFINITIONS

### M1 — User Service
**Owner LLM**: Claude
**Depends on**: Nothing (build first)
**Publishes**: `user.enrolled`, `user.role_changed`

```
Features:
- Student / teacher / admin profile management
- RBAC: 3 roles, granular permissions
- Onboarding flows per role
- Profile photo upload and management
- Account deactivation / re-activation
- Password reset via email OTP
- Multi-tenant isolation via college_id
- Face enrollment endpoint (stores encrypted FaceNet embedding)

REST contracts:
  POST   /users                        Create user
  GET    /users/{id}                   Get profile
  PATCH  /users/{id}                   Update profile
  PATCH  /users/{id}/role              Change role (admin only)
  POST   /users/{id}/face-enroll       Store encrypted face embedding
  POST   /auth/login                   Returns access + refresh tokens
  POST   /auth/refresh                 Rotate tokens
  POST   /auth/reset-password          OTP flow

DB tables: users, roles, permissions, role_permissions
```

---

### M2 — Academic Service
**Owner LLM**: Claude / Gemini
**Depends on**: M1 (teacher and student IDs)
**Publishes**: `session.created`, `timetable.updated`

```
Features:
- Department and course management
- Batch and section management (CS-A, CS-B etc.)
- Timetable: recurring and one-off classes
- Room assignment and conflict detection
- Teacher-course-batch assignment
- Academic calendar and holiday management
- Curriculum structure (subjects per semester)

REST contracts:
  GET/POST  /departments
  GET/POST  /courses
  GET/POST  /batches
  GET/POST  /rooms
  GET/POST  /timetable/{batch_id}
  POST      /timetable/check-conflict

DB tables: departments, courses, batches, sections, rooms, timetable_slots, academic_calendar
```

---

### M3 — Attendance Service
**Owner LLM**: Claude
**Depends on**: M1 (student), M2 (session), M8 (face verify)
**Publishes**: `attendance.marked`, `attendance.anomaly_detected`

```
Anti-proxy design — 3 independent layers:
  Layer 1: QR token = signed JWT (session_id + GPS centroid + expiry + nonce + HMAC-SHA256)
           Regenerates visually every 90s. Server validates signature + expiry.
  Layer 2: GPS — haversine distance from classroom centroid. Threshold: 100m. Flagged not rejected.
  Layer 3: Face — live frame → M8 (DeepFace FaceNet) → match/no-match. Frame discarded immediately.
  Anti-replay: device fingerprint + one-submit-per-device-per-session enforced.

Attendance state machine:
  PENDING → OPEN → SUBMITTED → VERIFIED → RECORDED
                             ↘ FLAGGED (manual teacher review)
  CLOSED (session ended, no further submissions)

REST contracts:
  POST  /sessions/{id}/qr              Generate QR token
  POST  /attendance/submit             Student submits QR + GPS + face frame
  GET   /attendance/{student_id}       Per-student attendance log
  GET   /attendance/session/{id}       Live feed for teacher
  PATCH /attendance/{id}/override      Teacher manual override (audit logged)
  GET   /attendance/report/{batch_id}  Exportable report

DB tables: class_sessions, qr_tokens, attendance_records, device_logs, attendance_overrides
```

---

### M4 — Marks Service
**Owner LLM**: Claude / Gemini
**Depends on**: M1 (users), M2 (courses/batches)
**Publishes**: `marks.updated`, `assessment.created`

```
Features:
- Assessment types: CIE 1/2/3, SEE, assignments, lab
- Teacher bulk CSV upload + manual entry
- Grade computation engine with configurable weightage
- Class statistics: mean, median, std dev per assessment
- Marks lock/unlock workflow
- Student performance history and trends
- Optional parent/guardian view

REST contracts:
  POST  /assessments                   Create assessment
  PUT   /marks/bulk                    CSV bulk upload
  PUT   /marks/{assessment_id}/{uid}   Single mark entry
  GET   /marks/{student_id}/history    All marks history
  GET   /marks/{assessment_id}/stats   Class statistics
  PATCH /assessments/{id}/lock         Lock/unlock

DB tables: assessments, marks, grade_rules, marks_audit
```

---

### M5 — Communication Service
**Owner LLM**: Claude / Gemini
**Depends on**: M1 (users), M2 (batches for targeting)
**Publishes**: `notification.queued`, `message.sent`

```
Features:
- Teacher → class/section announcements with attachments
- Teacher ↔ student direct messaging (threaded)
- Admin → college-wide broadcasts
- Notification queue: in-app, push (PWA), email digest
- Read receipts on announcements
- Message search and archive
- Scheduled announcements

REST contracts:
  POST  /announcements                 Create announcement
  GET   /announcements/{batch_id}      Fetch for batch
  POST  /messages                      Send DM
  GET   /messages/{thread_id}          Get thread
  GET   /notifications/{user_id}       Fetch notifications
  PATCH /notifications/{id}/read       Mark read

DB tables: announcements, messages, notification_queue, read_receipts
```

---

### M6 — Content Service
**Owner LLM**: Claude / Gemini
**Depends on**: M1 (teacher), M2 (course), triggers M7 ingestion
**Publishes**: `material.uploaded`, `material.updated`

```
Features:
- Uploads: PDF, PPTX, DOCX, YouTube URLs
- Metadata tagging: course, topic, difficulty, week
- Presigned R2 upload URLs (file never touches backend)
- Material versioning with changelog
- Student access control per course enrollment
- Triggers M7 ingestion pipeline on upload
- Engagement signal: which materials accessed most

REST contracts:
  POST  /materials/upload-url          Get presigned R2 URL
  POST  /materials                     Register metadata after upload
  GET   /materials/{course_id}         List materials for course
  PATCH /materials/{id}               Update metadata / new version
  GET   /materials/{id}/access-log     Engagement signal

DB tables: materials, material_tags, material_access, material_versions
```

---

### M7 — Learning Engine (AI Service)
**Owner LLM**: Claude
**Depends on**: M6 (material events), M1 (enrollment events)
**Publishes**: `ingestion.complete`, `learning_path.updated`
**Consumes**: `material.uploaded`, `user.enrolled`

```
RAG ingestion pipeline (triggered by material.uploaded):
  1. Extract: PDF → pdfplumber | PPTX → python-pptx | YouTube → youtube-transcript-api
  2. Clean: strip headers/footers, fix encoding, normalise whitespace
  3. Chunk: recursive splitter, chunk_size=512 tokens, overlap=64 tokens
  4. Embed: MiniLM-L6-v2 (local, zero cost), 384-dim
  5. Store: Qdrant collection per course, payload: {material_id, chunk_index, topic_tags, course_id, college_id}
  6. Index: HNSW, ef_construction=200, m=16

AI tutor interaction flow:
  1. Embed student query (MiniLM)
  2. Qdrant top-5 retrieval from enrolled courses
  3. Query student knowledge graph: mastered vs unknown concepts
  4. Assemble prompt: system role + chunks + graph context + query
  5. Gemini 1.5 Flash → response with inline citations
  6. Log interaction to PostgreSQL
  7. Update knowledge graph: concepts → "encountered"
  8. If marked helpful → concepts → "reinforced"

Knowledge graph:
  Node types:  Concept, Topic, Subject, Student (one graph per student)
  Edge types:  prerequisite_of, part_of, mastered_via, related_to
  Mastery:     unknown → encountered → practiced → mastered
  Storage MVP: NetworkX serialised to PostgreSQL JSONB → migrate Neo4j at scale

REST contracts (internal):
  POST  /tutor/chat                    Student asks question
  GET   /student/{id}/knowledge-graph  Graph snapshot
  GET   /student/{id}/learning-path    Personalised recommendations
  POST  /ingest                        Trigger ingestion for material
```

---

### M8 — Insights + Attendance ML (AI Service)
**Owner LLM**: Claude
**Depends on**: M3 (attendance events), M4 (marks events)
**Publishes**: `insight.generated`, `verification.result`
**Consumes**: `attendance.marked`, `marks.updated`, `material.uploaded`

```
Face verification design:
  - DeepFace FaceNet backbone
  - Liveness: MediaPipe Face Mesh blink/head-turn challenge (on-device, no video transmitted)
  - Flow: live frame → HTTPS → M8 → fetch stored embedding → cosine similarity → result → discard all
  - NEVER stored: submitted frame, live embedding
  - Stored ONLY: verification_confidence FLOAT in attendance_records

Risk signal model:
  Signal               Measurement                    Impact
  Attendance rate      Per subject, rolling 14d       Low → high urgency
  Attendance trend     Improving/declining 4 weeks    Declining → medium urgency
  Marks trajectory     Last 2 vs class average        Both below avg → high urgency
  Tutor engagement     Days since last AI interaction >7 days → low urgency
  Tutor topic gaps     Concepts not in graph          Large gaps before exam → medium
  Message response     No reply to teacher in 48h     Flagged

ML stack: XGBoost (risk scoring), rule engine (insight ranking), FaceNet (verification)
Max alerts per teacher per day: 5 (ranked by urgency)
Feedback loop: useful/not useful → retrain insight ranker

REST contracts (internal):
  POST  /verify/face                   Attendance face check
  GET   /teacher/{id}/insights         Ranked insight cards
  POST  /insights/{id}/feedback        Thumbs up/down
```

---

### M9 — Admin Portal + Analytics
**Owner LLM**: Claude / Gemini
**Depends on**: All modules (read-only consumer)
**Publishes**: `config.updated`

```
Features:
- College-wide user management + bulk CSV onboarding
- Course and timetable administration
- Department-level performance dashboards
- Attendance compliance reports (AICTE format)
- System health and usage metrics
- Feature flags and config management
- Data export (CSV/PDF) for regulatory submissions
- Audit log viewer: every sensitive action with actor + timestamp

REST contracts:
  GET   /admin/reports/{type}          Generate reports
  POST  /admin/users/bulk             CSV import
  GET   /admin/system/health          Health check
  GET   /admin/audit-logs             Filtered audit log
  PATCH /admin/config/{key}           Update feature flags

DB tables: audit_logs, feature_flags, system_config, college_config
```

---

## PRIVACY & COMPLIANCE (DPDP Act 2023)

```
Consent:           Explicit required before face biometric collection. Opt-out available
                   (fallback: teacher manual mark).
Purpose limit:     Face data only for attendance verification.
Data minimisation: Frame used for verification → immediately discarded. Embedding not stored.
Right to access:   Students request all personal data via Privacy Centre in app.
Right to erasure:  Student-initiated. Anonymised analytics retained for institutional reporting.
Breach notif:      Report to Data Protection Board within 72 hours.
Data fiduciary:    The college (BMSCE) is fiduciary. Metis is data processor → DPA agreement needed.

Face data technical policy:
  Enrolled photo → FaceNet embedding → stored AES-256 encrypted in users table.
  Decryption key: environment variable (NOT in database).
  Attendance submission: live frame → M8 → cosine similarity → result returned → frame + live embedding DELETED FROM MEMORY.
  Persisted: attendance_records.verification_confidence FLOAT only.
```

---

## LLM ORCHESTRATION

```
Fallback chain (in priority order):
  1. Gemini 1.5 Flash  — 1M tokens/day free, 1M context, primary
  2. Groq (Llama 3 8B) — 6000 RPM free, fast, use if Gemini rate-limited
  3. Ollama (local)    — Phi-3 or Gemma 2B, dev/test only

Embeddings: sentence-transformers all-MiniLM-L6-v2 — always local, always free
```

---

## 8-WEEK ROADMAP

```
Week 1  Foundation
        M1 User service (schema, auth endpoints, RBAC)
        JWT + refresh token flow, all role guards
        M2 Academic service (courses, batches, timetable CRUD)
        Next.js setup: App Router, Tailwind, auth pages
        PostgreSQL: all foundation tables migrated
        GitHub repo, README, first ADR

Week 2  Core Infrastructure
        M3 Attendance: QR gen, GPS verify, state machine
        Redis: QR token TTL, session storage
        WebSocket: live attendance feed
        Mobile PWA: camera + QR + GPS submission
        M5 Announcements (basic, no DM)
        Student dashboard: schedule + attendance %

Week 3  Marks + Content
        M4 Marks: assessments, entry, grade computation
        M6 Content: R2 presigned upload, metadata
        Teacher interface: marks entry, attendance mgmt, content upload
        Student interface: marks view, content library, performance chart
        M5 extended: DMs, notification queue
        Sentry integration

Week 4  AI Begins — DEMO MILESTONE
        M7 Ingestion pipeline: PDF, PPTX, YouTube
        Qdrant on Render, first embeddings
        M7 Basic RAG tutor: question → retrieve → LLM → citations
        Student interface: AI tutor screen
        Internal demo: all core features end-to-end
        Load test: 50 concurrent users

Week 5  AI Deepens
        M7 Knowledge graph per student (NetworkX → PostgreSQL JSONB)
        Graph updates after tutor interaction
        Personalised learning path generation
        M8 Face verification (DeepFace, liveness challenge)
        Integrate face verify into M3 attendance
        Student face enrollment screen

Week 6  Teacher Intelligence
        M8 Risk scoring (XGBoost on attendance + marks signals)
        Insight generation pipeline: signals → rank → display
        Teacher insights panel
        Insight feedback loop
        M9 Admin portal MVP
        DPDP compliance audit: consent flows, deletion

Week 7  Polish + Scale Prep
        DB query analysis, N+1 fixes
        Redis caching for timetable + marks
        PWA offline mode: cached schedule + marks
        Accessibility audit
        E2E tests: attendance, marks, tutor critical paths
        API docs, architecture wiki

Week 8  Deploy + Demo
        Production: Vercel + Render + Railway
        Seed real BMSCE course structure (mock data)
        Full demo run-through: student + teacher + admin journeys
        3-minute demo video
        GitHub: polish README, architecture diagrams, complete ADRs
        BMSCE contact outreach for pilot session
```

---

## ADR TEMPLATE

Every major technical decision goes in `docs/adr/ADR-NNN-title.md`.

```markdown
# ADR-NNN: [Decision Title]
## Status: Accepted | Superseded by ADR-XXX | Deprecated
## Context
What is the problem or situation being decided?
## Decision
What did we decide?
## Consequences
What are the trade-offs? What becomes easier? What becomes harder?
## Alternatives Considered
- Option A: [description] — rejected because [reason]
- Option B: [description] — rejected because [reason]
```

---

## SESSION PROTOCOL

### Starting a session
```
Tell Claude:
  "I am working on [MODULE NAME]. Here is the CLAUDE.md. [paste file]"
  
Claude will:
  1. Read module status table — identify what's done, what's not
  2. Read the active module state block below
  3. Open with: "Before I write any code, let me confirm the plan for this session..."
  4. Brainstorm/refine with you (questions, edge cases, design decisions)
  5. Write a session plan: what will be built, what will be skeleton vs full
  6. Build — skeleton first, then fill features
  7. End with runnable code + updated module state block for you to paste back
```

### Session contract (Claude must honour these)
```
✅ Skeleton rule: Module router/pages MUST be registered and returning 200/placeholder by session end
✅ No broken imports: every import must resolve
✅ No orphan code: every new file must be referenced somewhere
✅ Schema first: DB migrations written before service code
✅ Event contracts first: publish/subscribe wiring before business logic
✅ Brainstorm before code: at least 3 clarifying questions answered before first line
✅ One module per session: do not bleed into another module's territory
✅ Update state block: always produce updated ACTIVE MODULE STATE at end

UI CONTRACT (enforced every session, no exceptions):
✅ All features listed in the screen inventory for this module MUST be wired up — no silent omissions
✅ Use shadcn/ui components only — no custom-styled divs pretending to be components
✅ If a feature needs backend data, call the real endpoint (or stub endpoint) — no hardcoded fake arrays in JSX
✅ Forms must validate (react-hook-form + zod) before submitting
✅ Do NOT spend more than ~10% of session time on how something looks
✅ Flag any feature from the screen inventory that was intentionally skipped and WHY in the state block
```

### Commit message format
```
feat(attendance): add GPS haversine validation with 100m threshold
fix(users): resolve refresh token rotation race condition  
chore(schema): add college_id index to attendance_records
docs(adr): ADR-004 — Qdrant over Chroma for vector storage
```

---

## ACTIVE MODULE STATE
> This block is updated by Claude at the end of every session. Paste it back into this file.

```yaml
last_updated: "Session not yet started"
active_module: null
module_states:

  M1_user_service:
    status: not_started
    skeleton_live: false
    db_tables_created: []
    endpoints_implemented: []
    endpoints_stubbed: []
    events_wired: []
    ui_screens_completed: []
    ui_screens_skipped: []        # list items with reason e.g. "face-enrollment: needs M8"
    known_issues: []
    next_session_picks_up_at: "Start from scratch — build schema first"
    files_created: []

  M2_academic_service:
    status: not_started
    skeleton_live: false
    db_tables_created: []
    endpoints_implemented: []
    endpoints_stubbed: []
    events_wired: []
    ui_screens_completed: []
    ui_screens_skipped: []
    known_issues: []
    next_session_picks_up_at: "Depends on M1 completion"
    files_created: []

  M3_attendance_service:
    status: not_started
    skeleton_live: false
    db_tables_created: []
    endpoints_implemented: []
    endpoints_stubbed: []
    state_machine_implemented: false
    qr_generation: false
    gps_verification: false
    face_verify_integration: false
    anti_replay: false
    events_wired: []
    ui_screens_completed: []
    ui_screens_skipped: []
    known_issues: []
    next_session_picks_up_at: "Depends on M1, M2 completion"
    files_created: []

  M4_marks_service:
    status: not_started
    skeleton_live: false
    db_tables_created: []
    endpoints_implemented: []
    endpoints_stubbed: []
    grade_engine_implemented: false
    csv_upload: false
    events_wired: []
    ui_screens_completed: []
    ui_screens_skipped: []
    known_issues: []
    next_session_picks_up_at: "Depends on M1, M2 completion"
    files_created: []

  M5_comms_service:
    status: not_started
    skeleton_live: false
    db_tables_created: []
    endpoints_implemented: []
    endpoints_stubbed: []
    announcements: false
    direct_messages: false
    notification_queue: false
    events_wired: []
    ui_screens_completed: []
    ui_screens_skipped: []
    known_issues: []
    next_session_picks_up_at: "Depends on M1, M2 completion"
    files_created: []

  M6_content_service:
    status: not_started
    skeleton_live: false
    db_tables_created: []
    endpoints_implemented: []
    endpoints_stubbed: []
    r2_presigned_upload: false
    ingestion_trigger: false
    versioning: false
    events_wired: []
    ui_screens_completed: []
    ui_screens_skipped: []
    known_issues: []
    next_session_picks_up_at: "Depends on M1, M2 completion"
    files_created: []

  M7_learning_engine:
    status: not_started
    skeleton_live: false
    qdrant_collection_created: false
    ingestion_pipeline:
      pdf: false
      pptx: false
      youtube: false
    rag_tutor: false
    knowledge_graph: false
    learning_path: false
    events_wired: []
    ui_screens_completed: []
    ui_screens_skipped: []
    known_issues: []
    next_session_picks_up_at: "Depends on M6 completion"
    files_created: []

  M8_insights_face:
    status: not_started
    skeleton_live: false
    face_verify_endpoint: false
    liveness_detection: false
    risk_scoring_model: false
    insight_pipeline: false
    feedback_loop: false
    events_wired: []
    ui_screens_completed: []
    ui_screens_skipped: []
    known_issues: []
    next_session_picks_up_at: "Depends on M3, M4 completion"
    files_created: []

  M9_admin_analytics:
    status: not_started
    skeleton_live: false
    db_tables_created: []
    endpoints_implemented: []
    endpoints_stubbed: []
    dashboards: false
    bulk_onboarding: false
    audit_log_viewer: false
    events_wired: []
    ui_screens_completed: []
    ui_screens_skipped: []
    known_issues: []
    next_session_picks_up_at: "Depends on all modules"
    files_created: []

frontend:
  next_app_initialized: false
  tailwind_configured: false
  auth_pages: false
  student_shell: false
  teacher_shell: false
  admin_shell: false
  route_guards: false

infrastructure:
  supabase_project_created: false
  upstash_redis_created: false
  r2_bucket_created: false
  qdrant_deployed: false
  vercel_linked: false
  render_services: []
  sentry_configured: false
```

---

## STUDENT INTERFACE — SCREEN INVENTORY
> Implementation standard: shadcn/ui components only. Every item below must be wired and functional.
> Mark any skipped item explicitly in the session state block with a reason.

```
/student/dashboard
  - Today's schedule: Table (time | subject | room | teacher)
  - Attendance % per subject: Table with Badge (green ≥75%, amber 65–75%, red <65%)
  - Upcoming assessments: Card list (name | subject | days remaining)
  - AI tutor: last 3 messages as Card links → navigate to /student/tutor
  - Announcements: scrollable list, newest first
  - Notification count: Badge in nav
  - Streak: plain text "X day streak" next to tutor section

/student/schedule
  - Weekly view: Table (Mon–Sat × periods), cell = subject + room
  - Day view tab: list of today's classes with room + teacher
  - Recurring vs one-off: Badge on each row
  - Cancelled/holiday: strikethrough row + Badge
  - iCal export: Button → GET /schedule/export/ical
  - Click any class row → Dialog showing attendance history for that subject

/student/attendance
  - Per-subject summary: Table (subject | sessions attended | total | % | status Badge)
  - 75% VTU threshold line: text warning on any row below threshold
  - Impact projector: computed row "miss X more → drop below 75%"
  - Session log: Table (date | subject | status | teacher note if any)
  - QR scan button: full-screen Dialog → camera stream → submit GPS + face → toast result
  - Monthly calendar: grid of days, each cell colour-coded by overall attendance that day
  - Teacher-adjusted records: italic row + tooltip showing teacher note

/student/marks
  - Assessment table: Table (assessment name | type | marks | max | class avg | date entered)
  - Class rank + percentile: text above table e.g. "Rank 12 / 60 — 80th percentile"
  - Radar chart: recharts RadarChart, one axis per subject, score = avg marks %
  - Trend line: recharts LineChart, x = assessment date, y = marks %, one line per subject
  - Grade projection: computed text per subject "Need X/100 in SEE to pass / get distinction"
  - PDF download: Button → client-side PDF generation of marks table

/student/tutor
  - Chat window: scrollable message list (user right, AI left)
  - Input: Textarea + Send button
  - Source citations: collapsible section below each AI response (material name + chunk ref)
  - Knowledge graph: Table view (concept | mastery level | last encountered) — visual upgrade later
  - Study recommendations: 3 Card items (topic | reason | "Study now" button)
  - Session continuity: load last N messages on mount from API
  - Difficulty toggle: ToggleGroup "Simple" / "Deep"
  - Quiz mode: Button → Dialog → 5 questions generated → answer inputs → submit → score shown
  - Save answer: Button on each AI response → POST /student/notes

/student/communication
  - Tabs: Announcements | Direct Messages | Notifications
  - Announcements tab: list filtered by subject (Select), unread Badge per subject
    - Each item: title + body + attachments (download links) + timestamp
  - DM tab: list of teacher threads → click → chat-style message view
    - Message status: "Sent" / "Delivered" / "Read" text below each sent message
  - Notifications tab: list with mark-all-read Button
  - Notification preferences: Select per channel (push / email / in-app)

/student/profile
  - Form: name, email, phone (read-only fields from DB)
  - Enrolled courses: list
  - Face enrollment: Button → camera Dialog → capture → POST /users/{id}/face-enroll
  - Privacy centre: list of data categories held + "Request deletion" Button → POST /privacy/delete-request
  - Theme toggle: light / dark (localStorage + class on html element)
  - Change password: Form (current password | new | confirm) → POST /auth/change-password
```

---

## TEACHER INTERFACE — SCREEN INVENTORY
> Implementation standard: shadcn/ui components only. Every item below must be wired and functional.

```
/teacher/dashboard
  - Today's classes: Table (time | batch | subject | room | attendance taken? Badge)
  - Top 3 AI insights: Card list (student name | signal summary | urgency Badge)
    - Each card: "Message" button | "Flag" button
  - Classes with no attendance yet: highlighted rows in schedule table
  - Recent marks submissions: list (assessment | batch | submitted by | date)
  - Unread student messages: count Badge + list preview
  - Quick actions: Button row — "Start Class" | "Enter Marks" | "Post Announcement"

/teacher/attendance
  - Start class: Select batch + subject → Button generates QR
  - QR display: full-screen Dialog with QR code + countdown timer (90s refresh)
  - Live attendance feed: Table updating in real-time via WebSocket (student name | time | status)
  - Manual mark: Button per student row → toggle present/absent/late
  - Close session: Button → review Dialog → confirm → POST /attendance/session/{id}/close
  - Bulk edit: "Mark all present" Button then uncheck absences
  - Historical editor: DatePicker → load session → editable Table (changes audit-logged)
  - Report export: Select (student | subject | date range) → Button → CSV download

/teacher/marks
  - Select assessment: Select dropdowns (batch | subject | assessment type)
  - Student marks table: Table (name | USN | marks input field | flagged outlier Badge)
  - Live stats: computed row at bottom (mean | median | std dev) — updates as marks typed
  - CSV upload: FileInput + upload Button → validate → preview → confirm
  - Lock/unlock: Toggle per assessment → PATCH /assessments/{id}/lock
  - Marks history: Table (assessment | date | entered by | locked?)
  - Edit log: click any row → Dialog showing change history

/teacher/insights
  - Insight cards: Card list sorted by urgency (HIGH | MEDIUM | LOW Badge)
  - Each card shows: student name | signal breakdown | recommended action text
  - Per-card actions: "Message student" Button | "Schedule meeting" Button | "Flag for counsellor" Button
  - Class-level patterns: separate Card section (e.g. "DBMS Unit 3: 60% below average")
  - Feedback: thumbs-up / thumbs-down per card → POST /insights/{id}/feedback
  - Dismiss: Button + reason Select (handled / not applicable / wrong student)
  - Weekly digest: toggle subscription (stored in preferences)

/teacher/content
  - Upload: FileInput accepting PDF/PPTX/DOCX + separate Input for YouTube URL
  - Metadata form: Select (course | topic | difficulty: easy/medium/hard | week number)
  - Preview: show filename + size before publish
  - Publish: Button → POST presigned URL → upload → POST /materials
  - Ingestion status: Badge (pending | processing | complete | failed) — poll /materials/{id}/status
  - Material list: Table (name | type | week | difficulty | uploaded | access count)
  - Version management: "Upload new version" Button per row → Dialog
  - Schedule release: DateTimePicker per material → PATCH /materials/{id}

/teacher/communication
  - Post announcement: Form (title | body | Textarea | subject Select | attach file)
  - Multi-batch: MultiSelect for batch targeting
  - Schedule: DateTimePicker toggle → scheduled_at field
  - DM: list of student threads → click → chat view with read receipts
  - Message templates: Select pre-written template → fills form → editable before send
  - Broadcast: separate tab for admin-level college-wide (admin only)

/teacher/students/{id}
  - Profile card: photo | name | USN | batch | semester | contact
  - Attendance timeline: Table (subject | % | recent trend arrow)
  - Marks history: Table (assessment | marks | class avg | date)
  - AI activity: Table (date | topics studied | session duration)
  - Risk score: number (0–100) + contributing factors list
  - Private notes: Textarea → save → GET/POST /teacher/notes/{student_id} (not visible to student)
  - Interaction history: list of messages sent/received
```

---

## ADMIN INTERFACE — SCREEN INVENTORY
> Implementation standard: shadcn/ui components only. Every item below must be wired and functional.

```
/admin/users
  - User table: Table (name | email | role | batch | status | actions)
  - Filters: Select (role | department | status)
  - Bulk CSV import: FileInput → upload → validate → preview → confirm → POST /admin/users/bulk
  - Role management: inline Select per row → PATCH /users/{id}/role
  - Account activation/deactivation: Toggle per row
  - Onboarding status: Badge (invited | enrolled | active)

/admin/academic
  - Tabs: Departments | Courses | Batches | Rooms | Timetable | Calendar
  - Each tab: Table with Add/Edit/Delete (Dialog forms)
  - Timetable: grid editor — assign teacher + room + time per batch+subject
  - Conflict detection: inline warning if room/teacher double-booked
  - Calendar: mark holidays/events → affects timetable display globally

/admin/reports
  - Report type Select: attendance compliance | performance | department analytics
  - Filters: date range, department, batch
  - Preview: Table of report data
  - Export: "Download CSV" Button | "Download PDF" Button
  - AICTE format: dedicated Button for compliance export in required format

/admin/system
  - Health metrics: Cards showing API uptime | DB connections | Redis status | job queue length
  - Feature flags: Table (flag name | description | enabled Toggle)
  - Audit log: Table (timestamp | actor | action | entity | old value | new value) with filters
  - System config: key-value Table with inline edit (college name, thresholds, etc.)
  - Sentry error feed: link out to Sentry dashboard (external)
```

---

*Metis CLAUDE.md — v1.1 — Frontend: bare-bones functional MVP. Redesign deferred. Update MODULE STATUS TABLE and ACTIVE MODULE STATE after every session.*
