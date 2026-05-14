# AI_DEFERRAL_PLAN.md — Metis AI Layer Deferral & Integration Map

> Authoritative inventory of every place where the AI layer (M7 Learning Engine, M8 Insights + Face) plugs into the rest of Metis.
> The core platform (M1–M6, M9–M11) must work fully without M7 or M8 ever being built.
> When you're ready to build M7/M8, you should find every plug-in point listed here. No surprises.

---

## CORE PRINCIPLE

The Metis academic core is fully functional without AI. M7 and M8 are **purely additive**:

- M7 (Learning Engine) reads events, ingests content, and serves a `/tutor` API that the student UI can call. If M7 is offline, the student dashboard, course view, and all academic flows continue working — `/student/tutor` simply shows a "coming soon" placeholder.
- M8 (Insights + Face) reads events, computes risk scores and insights, serves `/insights` APIs, and provides a `face_verify` function that M3 calls. If M8 is offline, attendance still records (face check returns the stub's 0.95 confidence), teacher insights screen shows an empty state, and risk scoring is simply absent — no academic workflow blocks.

**No academic core code may import from `services/learning-engine/` or `services/insights-engine/`.** All integration is via:
1. Redis pub/sub events (one-way — core publishes, AI consumes)
2. HTTP API calls from core → AI services (with timeout + fallback to stub)
3. A clearly-defined swap interface for face verification

---

## DEFERRAL CONTRACT — WHAT SHIPS NOW

| Item | Built now | Deferred |
|---|---|---|
| `services/learning-engine/` scaffold (FastAPI, /health) | ✅ | — |
| `services/insights-engine/` scaffold (FastAPI, /health) | ✅ | — |
| Face verify stub (`face_stub.py`) | ✅ | DeepFace FaceNet integration |
| All event publishers in M3, M4, M6, M10, M11 | ✅ | Event subscribers in M7/M8 |
| `/student/tutor` placeholder route | ✅ | RAG tutor backend, Qdrant index |
| `/teacher/insights` empty state | ✅ | Risk scoring model, insight pipeline |
| AI service deployment topology (Railway envs configured) | ✅ | Actual deployment of M7/M8 services |
| HTTP client helpers (`ai_client.py`) | ✅ | Calls return stub data when AI offline |
| Feature flags (`AI_LEARNING_ENGINE_ENABLED`, `AI_INSIGHTS_ENGINE_ENABLED`) | ✅ | Set to false in env |
| ADR-100: AI Deferral Strategy | ✅ | — |

---

## INTEGRATION POINTS — COMPLETE INVENTORY

Every integration point Metis has with the AI layer. Each has: location in repo, what the stub returns, what M7/M8 will replace it with, and the contract the swap must honor.

### IP-1: Face Verification (M3 attendance)

**Location**: `services/api/app/modules/attendance/face_stub.py`

**Stub behavior** (current — ships in M3 rework):
```python
async def verify_face(
    *,
    user_id: UUID,
    live_frame_base64: str,
    enrolled_embedding: Optional[bytes] = None,
) -> FaceVerifyResult:
    """
    STUB: Always returns 0.95 confidence to indicate verification passed.
    When M8 lands, swap implementation to call DeepFace FaceNet.
    """
    return FaceVerifyResult(
        verified=True,
        confidence=0.95,
        method="stub",
        embedding=None,
        error=None,
    )
```

**M8 swap interface** (must honor):
```python
class FaceVerifyResult(BaseModel):
    verified: bool
    confidence: float           # 0.0–1.0
    method: Literal["stub", "facenet", "manual"]
    embedding: Optional[bytes]  # AES-256 encrypted; only at enrollment time
    error: Optional[str]
```

**Contract**:
- Function MUST be async.
- Function MUST NOT raise on AI service unavailability — return `verified=False, method="stub", error="..."` instead. Caller (M3) then falls back to QR-only verification.
- Live frame MUST be deleted from memory after verification — never persisted.
- `enrolled_embedding` is supplied by caller when verifying; M8 fetches from `users.face_embedding_encrypted` if present.
- Confidence threshold for "verified" lives in attendance config, not in this function.

**M3 caller**: `services/api/app/modules/attendance/service.py::record_attendance()` — passes live frame, gets result, persists only `verification_confidence FLOAT` and `verification_method VARCHAR`.

**DPDP compliance**: `face_stub.py` and any future `face_facenet.py` MUST include the comment block:
```python
# DPDP COMPLIANCE: This function receives a live frame for verification ONLY.
# The frame MUST be discarded after embedding extraction and similarity computation.
# Persisted data: verification_confidence (FLOAT), verification_method (VARCHAR).
# Embeddings are stored AES-256 encrypted; decryption key in env, not in DB.
```

---

### IP-2: Material Ingestion for RAG (M6 → M7)

**Location**: `services/api/app/modules/content/router.py::upload_material()`

**Stub behavior** (ships in M6):
- Material uploaded to R2 → row inserted in `materials` table
- Event published: `material.uploaded` with payload `{material_id, course_offering_id, file_url, file_type, uploaded_by_user_id, college_id}`
- Core API returns 201 to the client and continues
- **No AI processing happens.** Event sits in Redis stream until M7 consumer is built.

**M7 consumer** (built when ready):
```python
# services/learning-engine/app/consumers/material_ingest.py
async def handle_material_uploaded(event: MaterialUploadedEvent):
    """
    Triggered by Redis pub/sub on `material.uploaded`.
    1. Download from R2 (Cloudflare signed URL)
    2. Extract text (PyPDF2 / python-pptx / mammoth as appropriate)
    3. Chunk (recursive character splitter, 1000 tokens, 200 overlap)
    4. Embed (sentence-transformers MiniLM-L6-v2)
    5. Upsert to Qdrant collection `materials_{college_id}`
    6. Update `materials.ingestion_status = 'ingested'`
    7. Optionally extract concepts → write to knowledge graph (NetworkX initially)
    """
```

**Contract for M6 publishing**:
- Event published synchronously inside the upload transaction (so DB row + event are atomic)
- Payload schema is stable — see "EVENT PAYLOAD SCHEMAS" section below
- If M7 is offline, events queue up; on M7 restart, it processes backlog
- `materials.ingestion_status` enum: `pending | ingested | failed | not_applicable` — set to `pending` on upload, M7 transitions

**Schema-ready columns on `materials` (added in M6)**:
- `ingestion_status VARCHAR(20) DEFAULT 'pending' NOT NULL`
- `ingested_at TIMESTAMPTZ NULL`
- `chunk_count INTEGER DEFAULT 0 NOT NULL`
- `ingestion_error TEXT NULL`

These columns exist from M6 onward; M7 just writes to them when it lands.

---

### IP-3: Student Tutor (M7 → student UI)

**Frontend location**: `apps/web/app/(student)/tutor/page.tsx`

**Stub UI** (ships with student shell in M2 rework, refined in subsequent modules):
```tsx
export default function TutorPage() {
  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-2">Tutor</h1>
      <p className="text-muted-foreground">
        AI tutor coming soon. This will let you ask questions about your course materials.
      </p>
      <div className="mt-6 rounded border border-dashed p-8 text-center text-muted-foreground">
        Tutor is not yet enabled for this college.
      </div>
    </div>
  );
}
```

**M7 replacement**:
- Same route, full chat UI built on top
- Calls `POST /api/v1/tutor/ask` on the main API
- Main API checks `AI_LEARNING_ENGINE_ENABLED` flag, forwards to `services/learning-engine/ask` with timeout 30s
- If flag off or service unreachable → returns `503 Service Unavailable` with message
- UI shows the message; user sees graceful degradation, not a crash

**Backend stub** in `services/api/app/modules/ai_proxy/router.py`:
```python
@router.post("/tutor/ask")
async def tutor_ask(req: TutorAskRequest, current_user: User = Depends(get_current_user)):
    if not settings.AI_LEARNING_ENGINE_ENABLED:
        raise HTTPException(503, "Tutor not yet enabled.")
    return await ai_client.learning_engine.ask(req, user=current_user)
```

This file exists from day one, returning 503. M7 just turns the flag on.

---

### IP-4: Risk Scoring (M3/M4 → M8)

**Events consumed** (M8 subscriber, when built):
- `attendance.marked` — recompute attendance trend
- `attendance.overridden` — recompute with override applied
- `attendance.eligibility_crossed` — escalate alert priority
- `marks.entered` — recompute performance trend
- `marks.locked` — finalize an assessment's contribution
- `student.migrated` — invalidate caches for old offering; recompute for new
- `assignment.submitted` — feed engagement signal
- `assignment.graded` — feed performance signal

**M8 output**: writes to `student_risk_scores` table.

**Schema-ready table** (added in M8, NOT in M2 rework — pure M8 territory):
```sql
CREATE TABLE student_risk_scores (
  id UUID PRIMARY KEY,
  college_id UUID NOT NULL,
  student_id UUID NOT NULL,
  course_offering_id UUID NULL,    -- NULL = global student score
  overall_risk FLOAT NOT NULL,     -- 0.0–1.0
  attendance_risk FLOAT NOT NULL,
  performance_risk FLOAT NOT NULL,
  engagement_risk FLOAT NOT NULL,
  risk_factors JSONB NOT NULL,     -- [{factor: "attendance_below_85", weight: 0.4, ...}]
  computed_at TIMESTAMPTZ NOT NULL,
  model_version VARCHAR(20) NOT NULL,
  ...
);
```

**Until M8 ships**: this table doesn't exist. UI queries the API which checks the flag and returns empty arrays. **The teacher insights screen ships with the empty state, not broken.**

**Backend stub** in `services/api/app/modules/ai_proxy/router.py`:
```python
@router.get("/insights/student/{student_id}")
async def get_student_insights(student_id: UUID, ...):
    if not settings.AI_INSIGHTS_ENGINE_ENABLED:
        return {"risk_score": None, "factors": [], "insights": [], "enabled": False}
    return await ai_client.insights_engine.get_student(student_id)
```

---

### IP-5: Teacher Insights Panel (M8 → teacher UI)

**Frontend location**: `apps/web/app/(teacher)/insights/page.tsx`
                       `apps/web/app/(teacher)/courses/[id]/_components/InsightsTab.tsx`

**Stub UI** (ships in teacher course hub):
```tsx
export default function InsightsTab({ offeringId }: { offeringId: string }) {
  const { data } = useInsights(offeringId);  // calls API; returns {enabled: false} when stub
  if (!data?.enabled) {
    return (
      <div className="p-6 text-center text-muted-foreground">
        <p>Insights Engine is not yet enabled.</p>
        <p className="text-sm">
          When enabled, this panel will show class-wide risk indicators,
          performance trends, and AI-flagged students.
        </p>
      </div>
    );
  }
  return <InsightsContent data={data} />;  // only renders when M8 live
}
```

**M8 replacement**: same component, full data flow once `enabled: true` comes back. UI components for charts and risk tables are NOT built until M8 — only the empty state ships now.

---

### IP-6: Predictive Eligibility (M3 eligibility engine, optionally enhanced by M8)

**Where**: `services/api/app/core/eligibility.py::compute_eligibility()`

**Deterministic core (ships in M3 rework, never depends on AI)**:
```python
def compute_eligibility(
    student_id: UUID,
    course_offering_id: UUID,
    as_of: datetime,
) -> EligibilityResult:
    """
    PURE DETERMINISTIC function.
    No AI calls. Computes attendance %, CIE eligibility (60% per CIE), SEE eligibility (85%),
    internal marks threshold (40% main / 60% makeup).
    Returns current + threshold-based results only — never predictions.
    """
```

**Optional M8 enhancement** (when M8 lands):
- A separate function `predict_end_of_term_eligibility(student_id, offering_id)` returns *predicted* end-of-term eligibility based on current trends
- Lives in `services/insights-engine/`, NOT in core
- Student dashboard might show this as a labeled prediction; core dashboard still shows the deterministic current state

**UI policy**: student dashboard shows current eligibility (deterministic) prominently. Predicted eligibility, if shown, must be clearly labeled "Predicted based on current trends — actual eligibility may vary."

---

### IP-7: AI-Assisted Grading Suggestions (M11 assignments, future)

**Where (future)**: `apps/web/app/(teacher)/courses/[id]/assignments/[aid]/grade/[sid]/page.tsx`

**Current behavior**: teacher grades manually. No AI suggestion. Period.

**Future enhancement (M8 or later)**: a "Suggested mark" button calls an AI grading endpoint, returns a suggested mark + rubric breakdown. Teacher reviews and accepts/edits.

**Not built now.** No stub UI. No backend endpoint. No event. This is documented here so that when it's built, the team knows to:
- Add `POST /api/v1/grading/suggest` proxying to M8
- Add UI button only when `AI_INSIGHTS_ENGINE_ENABLED` flag is true
- Store suggestion + teacher's final mark + edit distance for model retraining

**Reason for deferral**: grading suggestions touch AAT components and could affect actual marks — too high-stakes for a stub. Build deliberately with rollback story.

---

### IP-8: Anomaly Detection on Attendance (M8, future)

**Where (future)**: M8 subscribes to `attendance.marked` events and flags anomalies:
- Same student verified in two locations within a minute
- Sudden spike of "verified" attendance for a previously low-engagement student
- Mass face-verify failures (camera issue or attempted bypass)

**Surfaces in**: `/admin/notifications` feed (admin gets anomaly alerts) and `/hod/dashboard` (HOD sees department-level anomalies).

**Current**: no anomaly detection. M8 will add this without changes to M3.

---

### IP-9: Knowledge Graph (M7, future)

**Where (future)**: `services/learning-engine/app/knowledge_graph/`

**Starts as**: NetworkX in-memory, persisted as pickle to R2 on each update. Nodes = concepts extracted from materials. Edges = "prerequisite-of", "related-to".

**Evolves to**: Neo4j (when scale demands it) — but the API the rest of Metis sees (`POST /api/v1/concepts/related`) stays stable.

**Used by**: tutor (concept lookup), insights (weak-topic detection in M8).

**Not built now.** No schema. No stub.

---

### IP-10: LLM Orchestration Layer (M7/M8 shared)

**Where (future)**: `services/api/app/core/llm_orchestrator.py` is built as part of the LLM-using module (likely M7 first).

**Strategy** (per CLAUDE.md tech stack):
1. Try Gemini 1.5 Flash (free tier first)
2. Fall back to Groq (faster, also free tier)
3. Fall back to local Ollama (when self-hosted)

**Current**: stub returns `{"choices": [{"text": "LLM not enabled"}]}` from `app/core/llm_stub.py`. Any module that imports it gets the stub until orchestrator is wired.

**Contract for orchestrator**:
- Single `async def complete(prompt: str, system: Optional[str], max_tokens: int) -> str` function
- Streaming version: `async def stream(...) -> AsyncIterator[str]`
- Cost tracking: every call writes to `llm_call_logs` table (token counts, cost, latency, model used)
- Rate limit handling: fail over to next provider on 429

---

## EVENT PAYLOAD SCHEMAS

These are the stable contracts. Once published, payload schema changes require versioning the event (`material.uploaded.v2`).

### `material.uploaded`
```json
{
  "event": "material.uploaded",
  "version": 1,
  "occurred_at": "2026-05-14T10:30:00Z",
  "college_id": "uuid",
  "actor_user_id": "uuid",
  "data": {
    "material_id": "uuid",
    "course_offering_id": "uuid",
    "title": "Linear Algebra Notes Week 1",
    "file_url": "r2://...",
    "file_type": "application/pdf",
    "file_size_bytes": 1024000,
    "topic": "linear-algebra",
    "uploaded_by_user_id": "uuid"
  }
}
```

### `attendance.marked`
```json
{
  "event": "attendance.marked",
  "version": 1,
  "occurred_at": "2026-05-14T10:30:00Z",
  "college_id": "uuid",
  "actor_user_id": "uuid",
  "data": {
    "attendance_record_id": "uuid",
    "class_session_id": "uuid",
    "course_offering_id": "uuid",
    "student_id": "uuid",
    "status": "present|absent|late|excused",
    "verification_method": "qr|face|manual|teacher_override",
    "verification_confidence": 0.95,
    "marked_at": "2026-05-14T10:30:00Z"
  }
}
```

### `marks.entered`
```json
{
  "event": "marks.entered",
  "version": 1,
  "occurred_at": "...",
  "college_id": "uuid",
  "actor_user_id": "uuid",
  "data": {
    "mark_id": "uuid",
    "assessment_id": "uuid",
    "course_offering_id": "uuid",
    "student_id": "uuid",
    "marks_obtained": 32.5,
    "max_marks": 40,
    "component_kind": "cie|aat|lab|assignment|see"
  }
}
```

### `assignment.submitted`
```json
{
  "event": "assignment.submitted",
  "version": 1,
  "occurred_at": "...",
  "college_id": "uuid",
  "actor_user_id": "uuid",
  "data": {
    "submission_id": "uuid",
    "assignment_id": "uuid",
    "course_offering_id": "uuid",
    "student_id": "uuid",
    "submitted_at": "...",
    "is_late": false,
    "file_urls": ["r2://..."]
  }
}
```

### `student.migrated` (HOD dissolves elective)
```json
{
  "event": "student.migrated",
  "version": 1,
  "occurred_at": "...",
  "college_id": "uuid",
  "actor_user_id": "uuid",
  "data": {
    "student_id": "uuid",
    "from_course_offering_id": "uuid",
    "to_course_offering_id": "uuid",
    "elective_group_id": "uuid",
    "reason": "elective_dissolved"
  }
}
```

(Full list in CLAUDE.md → EVENT BUS section.)

---

## REPO STRUCTURE — AI PLACEHOLDERS

```
metis/
├── services/
│   ├── api/
│   │   └── app/
│   │       ├── modules/
│   │       │   ├── attendance/
│   │       │   │   ├── face_stub.py          # IP-1 — stub, M8 swaps
│   │       │   │   └── service.py            # calls face verify abstraction
│   │       │   ├── content/
│   │       │   │   └── router.py             # IP-2 — publishes material.uploaded
│   │       │   └── ai_proxy/                 # NEW — proxies to M7/M8 when enabled
│   │       │       ├── router.py             # /tutor/ask, /insights/student/*
│   │       │       └── client.py             # ai_client.learning_engine, ai_client.insights_engine
│   │       └── core/
│   │           ├── eligibility.py            # IP-6 — pure deterministic, no AI
│   │           ├── event_bus.py              # Redis pub/sub publisher (M10d)
│   │           └── llm_stub.py               # IP-10 — returns "not enabled"
│   ├── learning-engine/                      # M7 scaffold
│   │   ├── app/
│   │   │   ├── main.py                       # FastAPI with /health
│   │   │   ├── consumers/                    # event subscribers (empty for now)
│   │   │   │   └── __init__.py
│   │   │   ├── knowledge_graph/              # IP-9 (empty for now)
│   │   │   │   └── __init__.py
│   │   │   └── tutor/                        # IP-3 (empty for now)
│   │   │       └── __init__.py
│   │   ├── pyproject.toml
│   │   └── Dockerfile
│   └── insights-engine/                      # M8 scaffold
│       ├── app/
│       │   ├── main.py                       # FastAPI with /health
│       │   ├── consumers/                    # IP-4 event subscribers (empty)
│       │   │   └── __init__.py
│       │   ├── face/                         # IP-1 future home (empty)
│       │   │   └── __init__.py
│       │   └── risk_scoring/                 # IP-4, IP-8 (empty)
│       │       └── __init__.py
│       ├── pyproject.toml
│       └── Dockerfile
└── apps/
    └── web/
        └── app/
            ├── (student)/
            │   └── tutor/page.tsx            # IP-3 — placeholder UI
            └── (teacher)/
                ├── insights/page.tsx          # IP-5 — placeholder
                └── courses/[id]/_components/
                    └── InsightsTab.tsx        # IP-5 — empty state
```

---

## SCAFFOLD MINIMUM (what M7/M8 services ship as during M2 rework)

### `services/learning-engine/app/main.py`
```python
from fastapi import FastAPI

app = FastAPI(title="Metis Learning Engine", version="0.0.1")

@app.get("/health")
async def health():
    return {"status": "ok", "service": "learning-engine", "enabled": False}

@app.get("/")
async def root():
    return {"service": "learning-engine", "status": "scaffold-only"}
```

### `services/insights-engine/app/main.py`
```python
from fastapi import FastAPI

app = FastAPI(title="Metis Insights Engine", version="0.0.1")

@app.get("/health")
async def health():
    return {"status": "ok", "service": "insights-engine", "enabled": False}

@app.get("/")
async def root():
    return {"service": "insights-engine", "status": "scaffold-only"}
```

### `services/learning-engine/Dockerfile` and `services/insights-engine/Dockerfile`
Standard Python + FastAPI Dockerfiles. Build target Railway-compatible. Deployed as separate Railway services so the topology is correct from day one — they just don't do anything useful yet.

---

## FEATURE FLAGS

In `services/api/app/core/config.py`:

```python
class Settings(BaseSettings):
    # ... existing settings ...

    # AI feature flags
    AI_LEARNING_ENGINE_ENABLED: bool = False
    AI_LEARNING_ENGINE_URL: str = "http://localhost:9001"
    AI_INSIGHTS_ENGINE_ENABLED: bool = False
    AI_INSIGHTS_ENGINE_URL: str = "http://localhost:9002"

    # Face verify
    FACE_VERIFY_METHOD: Literal["stub", "facenet"] = "stub"
    FACE_VERIFY_THRESHOLD: float = 0.6
```

These flags must be checked on **every** AI-touching code path before making external calls. Default to `False`. Only set to `True` after M7/M8 actually deploy.

---

## ai_client.py — the proxy layer

`services/api/app/modules/ai_proxy/client.py`:

```python
import httpx
from app.core.config import settings
from app.core.logging import logger

class _LearningEngineClient:
    def __init__(self):
        self.base_url = settings.AI_LEARNING_ENGINE_URL
        self.enabled = settings.AI_LEARNING_ENGINE_ENABLED

    async def ask(self, req, user):
        if not self.enabled:
            return {"answer": "Tutor not yet enabled.", "enabled": False}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.base_url}/ask",
                    json={**req.dict(), "user_id": str(user.id)},
                )
                resp.raise_for_status()
                return resp.json()
        except (httpx.TimeoutException, httpx.HTTPError) as e:
            logger.warning("learning_engine_unavailable", error=str(e))
            return {"answer": "Tutor temporarily unavailable.", "enabled": True, "error": str(e)}

class _InsightsEngineClient:
    def __init__(self):
        self.base_url = settings.AI_INSIGHTS_ENGINE_URL
        self.enabled = settings.AI_INSIGHTS_ENGINE_ENABLED

    async def get_student(self, student_id):
        if not self.enabled:
            return {"risk_score": None, "factors": [], "insights": [], "enabled": False}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.base_url}/student/{student_id}")
                resp.raise_for_status()
                return {**resp.json(), "enabled": True}
        except (httpx.TimeoutException, httpx.HTTPError) as e:
            logger.warning("insights_engine_unavailable", error=str(e))
            return {"risk_score": None, "factors": [], "insights": [], "enabled": True, "error": str(e)}

class AIClient:
    learning_engine = _LearningEngineClient()
    insights_engine = _InsightsEngineClient()

ai_client = AIClient()
```

This client is built once (probably during M2 rework or whenever the first IP needs it). All subsequent AI usage goes through this layer.

---

## WHEN YOU EVENTUALLY BUILD M7

Sessions to plan:
1. **M7a — Scaffolding + Qdrant setup**: deploy Qdrant cluster, wire Redis subscriber in learning-engine, create `materials_{college_id}` collection schema, write smoke-test ingestion of one document
2. **M7b — Full ingestion pipeline**: PDF/PPT/DOC extraction, chunking, embedding, Qdrant upsert; subscribe to `material.uploaded`; backfill all existing materials
3. **M7c — Tutor backend**: `/ask` endpoint, RAG retrieval, LLM orchestrator (Gemini Flash), context window management
4. **M7d — Tutor UI**: full chat interface, message history, citations
5. **M7e — Knowledge graph**: NetworkX initial, concept extraction from materials, "related concepts" endpoint

## WHEN YOU EVENTUALLY BUILD M8

Sessions to plan:
1. **M8a — Face verify**: DeepFace FaceNet integration, embedding storage (AES-256 encrypted), enrollment endpoint, swap `face_stub.py` → `face_facenet.py`
2. **M8b — Risk scoring v1**: subscribe to attendance/marks events, compute simple weighted score, populate `student_risk_scores` table
3. **M8c — Insights API**: `/insights/student/{id}`, `/insights/class/{offering_id}`, expose to teacher/HOD UIs
4. **M8d — Risk scoring v2**: train a real model on accumulated data (when there's enough signal), version models, A/B route
5. **M8e — Anomaly detection**: pattern detection on attendance, alert routing to admin/HOD

---

## VERIFICATION CHECKLIST — AI LAYER REMAINS OPTIONAL

Run periodically as you build M3 rework, M4 rework, M5, M6, M9, M10, M11. The platform must function fully with AI services completely offline.

- [ ] Stop `services/learning-engine/` and `services/insights-engine/` entirely. Confirm:
  - [ ] `/student/dashboard` loads with no errors
  - [ ] `/student/tutor` shows placeholder, doesn't crash
  - [ ] `/student/courses/{id}` loads with all tabs working
  - [ ] `/teacher/dashboard` loads
  - [ ] `/teacher/courses/{id}/insights` shows empty state, doesn't crash
  - [ ] `/teacher/insights` shows empty state, doesn't crash
  - [ ] Take attendance via QR — face check returns 0.95 (stub), attendance records
  - [ ] HOD dashboard loads, dissolves an elective, system cascades correctly
  - [ ] Hall ticket generates correctly with eligibility deterministic from `core/eligibility.py`
  - [ ] Grade card generates
  - [ ] M5 notifications fire on academic events
  - [ ] M11 assignments submit, grade
  - [ ] Material upload completes (R2 + DB row), event published (queued in Redis), no AI processing happens — `materials.ingestion_status = 'pending'` for all
- [ ] No `import` statements in `services/api/` or `apps/web/` reference `learning-engine` or `insights-engine` directly. All routing through `ai_client`.
- [ ] Searching `services/api/app/modules/` for "OpenAI", "Gemini", "Anthropic", "embedding", "faiss", "qdrant" returns no results (those live only in `services/learning-engine/` and `services/insights-engine/`).
- [ ] `core/eligibility.py` has no AI calls. `pytest tests/eligibility/` runs without any AI service mock.

---

## SUMMARY — WHAT YOU CAN TELL ANYONE READING THE CODE

> "Metis is a complete university operating system that works without AI. The AI layer (M7 Learning Engine and M8 Insights+Face) is built as a separate deployable component that consumes events from the core via Redis pub/sub and exposes APIs the core can call when AI feature flags are enabled. Until M7/M8 are deployed, the core operates with deterministic logic and the AI-touching UI surfaces show 'coming soon' placeholders. When M7/M8 are deployed, no core code changes — flags flip from false to true and the AI capabilities light up."

That's the contract. Honor it during every build session.

---

*AI Deferral Plan v1.0 — Build the AI layer last, but ship every integration point now. Stubs over absence. Flags over feature deletion. Events over imports.*
