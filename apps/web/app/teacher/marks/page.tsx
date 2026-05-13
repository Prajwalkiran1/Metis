"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { api, ApiError, type Page as ApiPage } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  Dialog,
  ErrorText,
  Field,
  Input,
  Loading,
  Select,
  Table,
  Td,
  Th,
} from "@/components/ui";

type CourseOffering = {
  id: string;
  course_id: string;
  section_id: string;
  teacher_user_id: string;
  academic_term: string;
  semester: number;
};

type Course = {
  id: string;
  code: string;
  title: string;
};

type Section = {
  id: string;
  name: string;
  batch_id: string;
};

type Assessment = {
  id: string;
  course_offering_id: string;
  type: AssessmentType;
  name: string;
  max_marks: string;
  weight_percent: string | null;
  scheduled_date: string | null;
  state: "draft" | "open" | "locked";
  locked_at: string | null;
  created_at: string;
};

type AssessmentType = "cie1" | "cie2" | "cie3" | "see" | "assignment" | "lab";

const ASSESSMENT_TYPES: AssessmentType[] = [
  "cie1",
  "cie2",
  "cie3",
  "see",
  "assignment",
  "lab",
];

type RosterRow = {
  student_user_id: string;
  name: string;
  usn: string | null;
  mark_id: string | null;
  marks_obtained: string | null;
  is_absent: boolean;
  state: "entered" | "locked" | null;
};

type Stats = {
  count: number;
  absent_count: number;
  mean: number | null;
  median: number | null;
  stddev: number | null;
  min: number | null;
  max: number | null;
  max_marks: number;
  locked: boolean;
};

type BulkResponse = {
  committed: number;
  errors: { row_number: number; student_uid: string | null; code: string; message: string }[];
  dry_run: boolean;
};

type AuditEntry = {
  id: number;
  action: string;
  old_value: Record<string, unknown> | null;
  new_value: Record<string, unknown> | null;
  reason: string | null;
  actor_user_id: string;
  created_at: string;
};

export default function TeacherMarksPage() {
  const [offerings, setOfferings] = useState<CourseOffering[]>([]);
  const [coursesById, setCoursesById] = useState<Record<string, Course>>({});
  const [sectionsById, setSectionsById] = useState<Record<string, Section>>({});
  const [selectedOfferingId, setSelectedOfferingId] = useState<string | null>(null);

  const [assessments, setAssessments] = useState<Assessment[]>([]);
  const [selectedAssessmentId, setSelectedAssessmentId] = useState<string | null>(null);

  const [roster, setRoster] = useState<RosterRow[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [draftMarks, setDraftMarks] = useState<Record<string, { value: string; absent: boolean }>>({});
  const [saving, setSaving] = useState<Record<string, boolean>>({});
  const [savedAt, setSavedAt] = useState<Record<string, number>>({});

  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [createForm, setCreateForm] = useState({
    type: "cie1" as AssessmentType,
    name: "",
    max_marks: "30",
    scheduled_date: "",
  });
  const [createErr, setCreateErr] = useState<string | null>(null);

  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvPreview, setCsvPreview] = useState<BulkResponse | null>(null);
  const [csvSubmitting, setCsvSubmitting] = useState(false);
  const [csvErr, setCsvErr] = useState<string | null>(null);

  const [lockBusy, setLockBusy] = useState(false);

  const [auditFor, setAuditFor] = useState<RosterRow | null>(null);
  const [auditRows, setAuditRows] = useState<AuditEntry[]>([]);
  const [auditErr, setAuditErr] = useState<string | null>(null);

  // ── 1. Load teacher's offerings + courses + sections ─────────────────────
  useEffect(() => {
    (async () => {
      try {
        const me = await api<{ id: string }>("/users/me");
        const offs = await api<ApiPage<CourseOffering>>("/course-offerings", {
          query: { teacher_user_id: me.id, limit: 200 },
        });
        setOfferings(offs.items);
        const courses = await api<ApiPage<Course>>("/courses", { query: { limit: 200 } });
        setCoursesById(Object.fromEntries(courses.items.map((c) => [c.id, c])));
        const sections = await api<ApiPage<Section>>("/sections", { query: { limit: 200 } });
        setSectionsById(Object.fromEntries(sections.items.map((s) => [s.id, s])));
      } catch (e) {
        setErr(e instanceof ApiError ? e.message : "failed to load");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  // ── 2. When offering changes, load its assessments ───────────────────────
  useEffect(() => {
    if (!selectedOfferingId) {
      setAssessments([]);
      setSelectedAssessmentId(null);
      return;
    }
    (async () => {
      try {
        const r = await api<ApiPage<Assessment>>("/assessments", {
          query: { course_offering_id: selectedOfferingId, limit: 200 },
        });
        setAssessments(r.items);
        setSelectedAssessmentId(r.items[0]?.id ?? null);
      } catch (e) {
        setErr(e instanceof ApiError ? e.message : "failed to load assessments");
      }
    })();
  }, [selectedOfferingId]);

  // ── 3. When assessment changes, load roster + stats ──────────────────────
  const reloadRosterAndStats = useCallback(async () => {
    if (!selectedAssessmentId) {
      setRoster([]);
      setStats(null);
      setDraftMarks({});
      return;
    }
    try {
      const [rows, s] = await Promise.all([
        api<RosterRow[]>(`/assessments/${selectedAssessmentId}/roster`),
        api<Stats>(`/assessments/${selectedAssessmentId}/stats`),
      ]);
      setRoster(rows);
      setStats(s);
      const draft: Record<string, { value: string; absent: boolean }> = {};
      for (const r of rows) {
        draft[r.student_user_id] = {
          value: r.marks_obtained ?? "",
          absent: r.is_absent,
        };
      }
      setDraftMarks(draft);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "failed to load roster");
    }
  }, [selectedAssessmentId]);

  useEffect(() => {
    void reloadRosterAndStats();
  }, [reloadRosterAndStats]);

  const selectedAssessment = useMemo(
    () => assessments.find((a) => a.id === selectedAssessmentId) ?? null,
    [assessments, selectedAssessmentId],
  );
  const locked = selectedAssessment?.state === "locked";

  // ── Client-side live stats from draftMarks ───────────────────────────────
  const liveStats = useMemo(() => {
    const nums: number[] = [];
    let absent = 0;
    let count = 0;
    for (const { value, absent: ab } of Object.values(draftMarks)) {
      if (ab) {
        absent += 1;
        count += 1;
        continue;
      }
      if (value === "") continue;
      const n = Number(value);
      if (Number.isFinite(n)) {
        nums.push(n);
        count += 1;
      }
    }
    nums.sort((a, b) => a - b);
    const mean = nums.length ? nums.reduce((a, b) => a + b, 0) / nums.length : null;
    const median = nums.length
      ? (nums.length % 2 === 1
          ? nums[(nums.length - 1) / 2]
          : (nums[nums.length / 2 - 1] + nums[nums.length / 2]) / 2)
      : null;
    let stddev: number | null = null;
    if (nums.length > 1 && mean !== null) {
      const v = nums.reduce((a, b) => a + (b - mean) ** 2, 0) / (nums.length - 1);
      stddev = Math.sqrt(v);
    }
    return {
      count,
      absent,
      mean,
      median,
      stddev,
      min: nums[0] ?? null,
      max: nums[nums.length - 1] ?? null,
    };
  }, [draftMarks]);

  const saveMark = useCallback(
    async (uid: string) => {
      if (!selectedAssessmentId) return;
      const draft = draftMarks[uid];
      if (!draft) return;
      // Validate locally before hitting the API.
      if (!draft.absent && draft.value === "") return;
      setSaving((p) => ({ ...p, [uid]: true }));
      try {
        const body = draft.absent
          ? { is_absent: true }
          : { is_absent: false, marks_obtained: draft.value };
        await api(`/marks/${selectedAssessmentId}/${uid}`, {
          method: "PUT",
          body,
        });
        setSavedAt((p) => ({ ...p, [uid]: Date.now() }));
        // Pull fresh stats (server-authoritative) without disturbing inputs.
        const s = await api<Stats>(`/assessments/${selectedAssessmentId}/stats`);
        setStats(s);
        // Reload roster (only to pick up the new mark_id for the audit Dialog).
        const rows = await api<RosterRow[]>(
          `/assessments/${selectedAssessmentId}/roster`,
        );
        setRoster(rows);
      } catch (e) {
        const msg = e instanceof ApiError ? e.message : "save failed";
        alert(`Save failed for ${uid.slice(0, 8)}: ${msg}`);
      } finally {
        setSaving((p) => ({ ...p, [uid]: false }));
      }
    },
    [draftMarks, selectedAssessmentId],
  );

  const onCreateAssessment = useCallback(async () => {
    if (!selectedOfferingId) return;
    setCreateErr(null);
    try {
      const a = await api<Assessment>("/assessments", {
        method: "POST",
        body: {
          course_offering_id: selectedOfferingId,
          type: createForm.type,
          name: createForm.name.trim(),
          max_marks: createForm.max_marks,
          scheduled_date: createForm.scheduled_date || undefined,
        },
      });
      setAssessments((prev) => [a, ...prev]);
      setSelectedAssessmentId(a.id);
      setCreateOpen(false);
      setCreateForm({ type: "cie1", name: "", max_marks: "30", scheduled_date: "" });
    } catch (e) {
      setCreateErr(e instanceof ApiError ? e.message : "create failed");
    }
  }, [createForm, selectedOfferingId]);

  const onValidateCsv = useCallback(async () => {
    if (!csvFile || !selectedAssessmentId) return;
    setCsvErr(null);
    setCsvSubmitting(true);
    try {
      const fd = new FormData();
      fd.append("file", csvFile);
      fd.append("assessment_id", selectedAssessmentId);
      fd.append("dry_run", "true");
      const r = await api<BulkResponse>("/marks/bulk", {
        method: "PUT",
        body: fd,
      });
      setCsvPreview(r);
    } catch (e) {
      setCsvErr(e instanceof ApiError ? e.message : "csv validate failed");
    } finally {
      setCsvSubmitting(false);
    }
  }, [csvFile, selectedAssessmentId]);

  const onCommitCsv = useCallback(async () => {
    if (!csvFile || !selectedAssessmentId) return;
    setCsvErr(null);
    setCsvSubmitting(true);
    try {
      const fd = new FormData();
      fd.append("file", csvFile);
      fd.append("assessment_id", selectedAssessmentId);
      fd.append("dry_run", "false");
      const r = await api<BulkResponse>("/marks/bulk", {
        method: "PUT",
        body: fd,
      });
      setCsvPreview(r);
      setCsvFile(null);
      await reloadRosterAndStats();
    } catch (e) {
      setCsvErr(e instanceof ApiError ? e.message : "csv commit failed");
    } finally {
      setCsvSubmitting(false);
    }
  }, [csvFile, selectedAssessmentId, reloadRosterAndStats]);

  const onToggleLock = useCallback(
    async (lock: boolean) => {
      if (!selectedAssessmentId) return;
      let reason: string | null = null;
      if (!lock) {
        reason = prompt("Reason for unlocking?") ?? null;
        if (!reason) return;
      } else if (!confirm("Lock this assessment? Marks will become read-only.")) {
        return;
      }
      setLockBusy(true);
      try {
        const a = await api<Assessment>(
          `/assessments/${selectedAssessmentId}/lock`,
          { method: "PATCH", body: { lock, reason: reason || undefined } },
        );
        setAssessments((prev) => prev.map((x) => (x.id === a.id ? a : x)));
        await reloadRosterAndStats();
      } catch (e) {
        alert(e instanceof ApiError ? e.message : "lock toggle failed");
      } finally {
        setLockBusy(false);
      }
    },
    [selectedAssessmentId, reloadRosterAndStats],
  );

  const openAudit = useCallback(async (row: RosterRow) => {
    setAuditFor(row);
    setAuditRows([]);
    setAuditErr(null);
    if (!row.mark_id) return;
    try {
      const rows = await api<AuditEntry[]>(`/marks/${row.mark_id}/audit`);
      setAuditRows(rows);
    } catch (e) {
      setAuditErr(e instanceof ApiError ? e.message : "failed to load audit");
    }
  }, []);

  // ── Outlier detection: |z| > 2 against current draft mean/stddev ────────
  const outlierFor = useCallback(
    (uid: string) => {
      const d = draftMarks[uid];
      if (!d || d.absent || d.value === "") return false;
      const n = Number(d.value);
      if (!Number.isFinite(n)) return false;
      if (liveStats.mean === null || !liveStats.stddev || liveStats.stddev === 0) {
        return false;
      }
      const z = Math.abs((n - liveStats.mean) / liveStats.stddev);
      return z > 2;
    },
    [draftMarks, liveStats],
  );

  if (loading) return <Loading />;

  return (
    <div className="space-y-6">
      <h1 className="text-lg font-semibold text-zinc-900">Marks</h1>
      <ErrorText>{err}</ErrorText>

      <Card className="p-4">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <Field label="Course offering">
            <Select
              value={selectedOfferingId ?? ""}
              onChange={(e) => setSelectedOfferingId(e.target.value || null)}
            >
              <option value="">Select…</option>
              {offerings.map((o) => {
                const c = coursesById[o.course_id];
                const s = sectionsById[o.section_id];
                return (
                  <option key={o.id} value={o.id}>
                    {c ? `${c.code} · ${c.title}` : o.course_id.slice(0, 8)}
                    {s ? ` · Sec ${s.name}` : ""} · {o.academic_term}
                  </option>
                );
              })}
            </Select>
          </Field>
          <Field label="Assessment">
            <Select
              value={selectedAssessmentId ?? ""}
              onChange={(e) => setSelectedAssessmentId(e.target.value || null)}
              disabled={!selectedOfferingId}
            >
              <option value="">Select…</option>
              {assessments.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.type.toUpperCase()} · {a.name} · /{a.max_marks}
                  {a.state === "locked" ? " 🔒" : ""}
                </option>
              ))}
            </Select>
          </Field>
          <div className="flex items-end gap-2">
            <Button
              type="button"
              variant="secondary"
              disabled={!selectedOfferingId}
              onClick={() => setCreateOpen(true)}
            >
              + New
            </Button>
            {selectedAssessment ? (
              <Button
                type="button"
                variant={locked ? "danger" : "secondary"}
                disabled={lockBusy}
                onClick={() => onToggleLock(!locked)}
              >
                {locked ? "Unlock" : "Lock"}
              </Button>
            ) : null}
          </div>
        </div>
      </Card>

      {selectedAssessment ? (
        <>
          <Card className="overflow-hidden">
            <div className="border-b border-zinc-200 bg-zinc-50 px-4 py-2 text-xs text-zinc-600">
              {selectedAssessment.type.toUpperCase()} · {selectedAssessment.name} · max {selectedAssessment.max_marks}{" "}
              {locked ? <Badge tone="red">locked</Badge> : <Badge tone="green">{selectedAssessment.state}</Badge>}
            </div>
            <Table>
              <thead>
                <tr>
                  <Th>USN</Th>
                  <Th>Name</Th>
                  <Th>Marks</Th>
                  <Th>Absent</Th>
                  <Th>Flag</Th>
                  <Th>Saved</Th>
                  <Th></Th>
                </tr>
              </thead>
              <tbody>
                {roster.map((row) => {
                  const draft = draftMarks[row.student_user_id] ?? { value: "", absent: false };
                  const isOutlier = outlierFor(row.student_user_id);
                  return (
                    <tr key={row.student_user_id}>
                      <Td className="font-mono text-xs">{row.usn ?? "—"}</Td>
                      <Td>{row.name}</Td>
                      <Td>
                        <Input
                          type="number"
                          value={draft.value}
                          disabled={draft.absent || locked}
                          onChange={(e) =>
                            setDraftMarks((p) => ({
                              ...p,
                              [row.student_user_id]: {
                                value: e.target.value,
                                absent: p[row.student_user_id]?.absent ?? false,
                              },
                            }))
                          }
                          onBlur={() => saveMark(row.student_user_id)}
                          className="w-24"
                        />
                      </Td>
                      <Td>
                        <input
                          type="checkbox"
                          checked={draft.absent}
                          disabled={locked}
                          onChange={(e) => {
                            setDraftMarks((p) => ({
                              ...p,
                              [row.student_user_id]: {
                                value: e.target.checked
                                  ? ""
                                  : p[row.student_user_id]?.value ?? "",
                                absent: e.target.checked,
                              },
                            }));
                            // Save immediately on toggle.
                            setTimeout(() => saveMark(row.student_user_id), 0);
                          }}
                        />
                      </Td>
                      <Td>{isOutlier ? <Badge tone="amber">outlier</Badge> : null}</Td>
                      <Td className="text-xs text-zinc-500">
                        {saving[row.student_user_id] ? "saving…" : ""}
                        {savedAt[row.student_user_id] && !saving[row.student_user_id] ? "✓" : ""}
                      </Td>
                      <Td>
                        {row.mark_id ? (
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            onClick={() => openAudit(row)}
                          >
                            history
                          </Button>
                        ) : null}
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot>
                <tr className="bg-zinc-50">
                  <Td colSpan={2} className="text-xs font-medium text-zinc-700">
                    Stats ({liveStats.count} entered / {liveStats.absent} absent)
                  </Td>
                  <Td className="text-xs">
                    mean: {liveStats.mean?.toFixed(2) ?? "—"}
                  </Td>
                  <Td className="text-xs">median: {liveStats.median?.toFixed(2) ?? "—"}</Td>
                  <Td className="text-xs">stddev: {liveStats.stddev?.toFixed(2) ?? "—"}</Td>
                  <Td className="text-xs">
                    {stats ? `server: μ=${stats.mean?.toFixed(2) ?? "—"} σ=${stats.stddev?.toFixed(2) ?? "—"}` : ""}
                  </Td>
                  <Td></Td>
                </tr>
              </tfoot>
            </Table>
          </Card>

          <Card className="p-4">
            <h2 className="mb-3 text-sm font-medium text-zinc-900">CSV bulk upload</h2>
            <p className="mb-3 text-xs text-zinc-500">
              Headers: <code>student_uid,marks_obtained,is_absent</code>. Valid rows commit; invalid rows are returned with error codes.
            </p>
            <div className="flex items-center gap-2">
              <input
                type="file"
                accept=".csv,text/csv"
                disabled={locked}
                onChange={(e) => {
                  setCsvFile(e.target.files?.[0] ?? null);
                  setCsvPreview(null);
                }}
              />
              <Button
                type="button"
                variant="secondary"
                disabled={!csvFile || csvSubmitting || locked}
                onClick={onValidateCsv}
              >
                {csvSubmitting ? "…" : "Validate"}
              </Button>
              {csvPreview && csvPreview.dry_run ? (
                <Button
                  type="button"
                  disabled={csvSubmitting || locked}
                  onClick={onCommitCsv}
                >
                  Commit ({csvPreview.committed})
                </Button>
              ) : null}
            </div>
            <ErrorText>{csvErr}</ErrorText>
            {csvPreview ? (
              <div className="mt-3 space-y-2 text-xs">
                <p className="text-zinc-700">
                  {csvPreview.dry_run ? "Preview" : "Committed"}: {csvPreview.committed} row(s) · {csvPreview.errors.length} error(s)
                </p>
                {csvPreview.errors.length ? (
                  <Table>
                    <thead>
                      <tr>
                        <Th>row</Th>
                        <Th>student_uid</Th>
                        <Th>code</Th>
                        <Th>message</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {csvPreview.errors.map((e, i) => (
                        <tr key={i}>
                          <Td>{e.row_number}</Td>
                          <Td className="font-mono">{e.student_uid ?? "—"}</Td>
                          <Td>
                            <Badge tone="red">{e.code}</Badge>
                          </Td>
                          <Td>{e.message}</Td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                ) : null}
              </div>
            ) : null}
          </Card>

          <Card className="p-4">
            <h2 className="mb-3 text-sm font-medium text-zinc-900">Assessments for this offering</h2>
            <Table>
              <thead>
                <tr>
                  <Th>Type</Th>
                  <Th>Name</Th>
                  <Th>Max</Th>
                  <Th>Date</Th>
                  <Th>State</Th>
                </tr>
              </thead>
              <tbody>
                {assessments.map((a) => (
                  <tr
                    key={a.id}
                    className={
                      a.id === selectedAssessmentId ? "bg-zinc-50" : ""
                    }
                  >
                    <Td>{a.type.toUpperCase()}</Td>
                    <Td>{a.name}</Td>
                    <Td>{a.max_marks}</Td>
                    <Td className="text-xs">{a.scheduled_date ?? "—"}</Td>
                    <Td>
                      {a.state === "locked" ? (
                        <Badge tone="red">locked</Badge>
                      ) : (
                        <Badge tone="green">{a.state}</Badge>
                      )}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card>
        </>
      ) : null}

      {/* Create assessment Dialog */}
      <Dialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="New assessment"
        footer={
          <>
            <Button variant="ghost" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button onClick={onCreateAssessment} disabled={!createForm.name}>
              Create
            </Button>
          </>
        }
      >
        <Field label="Type">
          <Select
            value={createForm.type}
            onChange={(e) =>
              setCreateForm((p) => ({ ...p, type: e.target.value as AssessmentType }))
            }
          >
            {ASSESSMENT_TYPES.map((t) => (
              <option key={t} value={t}>
                {t.toUpperCase()}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Name">
          <Input
            value={createForm.name}
            placeholder="e.g. CIE 1 — DBMS"
            onChange={(e) => setCreateForm((p) => ({ ...p, name: e.target.value }))}
          />
        </Field>
        <Field label="Max marks">
          <Input
            type="number"
            value={createForm.max_marks}
            onChange={(e) => setCreateForm((p) => ({ ...p, max_marks: e.target.value }))}
          />
        </Field>
        <Field label="Scheduled date (optional)">
          <Input
            type="date"
            value={createForm.scheduled_date}
            onChange={(e) =>
              setCreateForm((p) => ({ ...p, scheduled_date: e.target.value }))
            }
          />
        </Field>
        <ErrorText>{createErr}</ErrorText>
      </Dialog>

      {/* Mark audit Dialog */}
      <Dialog
        open={auditFor !== null}
        onClose={() => setAuditFor(null)}
        title={auditFor ? `History · ${auditFor.name}` : ""}
      >
        {auditErr ? <ErrorText>{auditErr}</ErrorText> : null}
        {auditRows.length === 0 ? (
          <p className="text-sm text-zinc-500">No history yet.</p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>When</Th>
                <Th>Action</Th>
                <Th>Old → New</Th>
                <Th>Reason</Th>
              </tr>
            </thead>
            <tbody>
              {auditRows.map((r) => (
                <tr key={r.id}>
                  <Td className="text-xs">{new Date(r.created_at).toLocaleString()}</Td>
                  <Td className="text-xs">{r.action}</Td>
                  <Td className="text-xs">
                    {(r.old_value?.marks_obtained ?? "—") + " → " + (r.new_value?.marks_obtained ?? "—")}
                  </Td>
                  <Td className="text-xs">{r.reason ?? ""}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Dialog>
    </div>
  );
}
