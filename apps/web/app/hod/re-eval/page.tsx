"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, api } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  ErrorText,
  Field,
  Loading,
  Select,
  Table,
  Td,
  Th,
} from "@/components/ui";

type SetupList = { id: string; state: string; academic_term_id: string };
type CourseAssignment = {
  id: string;
  course_code: string;
  course_title: string;
  course_type: string;
  section_name: string;
};
type SetupDetail = { id: string; courses: CourseAssignment[] };
type Term = { id: string; code: string };

type ReEval = {
  id: string;
  enrollment_id: number;
  student_user_id: string;
  student_name: string | null;
  usn: string | null;
  course_offering_id: string | null;
  course_code: string | null;
  requested_at: string;
  status: "requested" | "processing" | "completed" | "rejected";
  original_marks: number | null;
  revised_marks: number | null;
  outcome: "improved" | "held" | "rejected" | null;
  reason: string | null;
};

export default function HodReEvalPage() {
  const [setups, setSetups] = useState<SetupList[] | null>(null);
  const [terms, setTerms] = useState<Term[]>([]);
  const [setupId, setSetupId] = useState("");
  const [setupDetail, setSetupDetail] = useState<SetupDetail | null>(null);
  const [offeringId, setOfferingId] = useState("");
  const [requests, setRequests] = useState<ReEval[] | null>(null);
  const [csv, setCsv] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const reloadAll = useCallback(async () => {
    try {
      const [s, t] = await Promise.all([
        api<SetupList[]>("/workflow/semester-setups"),
        api<Term[]>("/academic-terms").catch(() => [] as Term[]),
      ]);
      const usable = s.filter((x) => x.state !== "draft");
      setSetups(usable);
      setTerms(t);
      if (usable.length > 0 && !setupId) setSetupId(usable[0].id);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "load failed");
    }
  }, [setupId]);

  const reloadDetail = useCallback(async () => {
    if (!setupId) return;
    try {
      const d = await api<SetupDetail>(`/workflow/semester-setups/${setupId}`);
      setSetupDetail(d);
      if (d.courses.length > 0 && !offeringId) setOfferingId(d.courses[0].id);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "load failed");
    }
  }, [setupId, offeringId]);

  const reloadRequests = useCallback(async () => {
    if (!offeringId) {
      setRequests([]);
      return;
    }
    try {
      const rows = await api<ReEval[]>("/workflow/re-evaluations", {
        query: { course_offering_id: offeringId },
      });
      setRequests(rows);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "load failed");
    }
  }, [offeringId]);

  useEffect(() => {
    reloadAll();
  }, [reloadAll]);
  useEffect(() => {
    reloadDetail();
  }, [reloadDetail]);
  useEffect(() => {
    reloadRequests();
  }, [reloadRequests]);

  const parsedRows = useMemo(() => {
    return csv
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line && !line.startsWith("#"))
      .map((line) => {
        const [usn, marks] = line.split(/[,\t]/).map((s) => s.trim());
        return { usn, revised_marks: Number(marks) };
      })
      .filter((r) => r.usn && !Number.isNaN(r.revised_marks));
  }, [csv]);

  async function onUpload() {
    if (!offeringId || parsedRows.length === 0) return;
    setBusy("upload");
    setActionErr(null);
    try {
      const out = await api<{
        processed: number;
        improved: number;
        held: number;
        rejected: { usn: string; reason: string }[];
      }>("/workflow/re-evaluations/upload", {
        method: "POST",
        body: { course_offering_id: offeringId, rows: parsedRows },
      });
      setActionErr(
        `Processed ${out.processed} (${out.improved} improved, ${out.held} held). Rejected ${out.rejected.length}.`,
      );
      setCsv("");
      await reloadRequests();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "upload failed");
    } finally {
      setBusy(null);
    }
  }

  if (err) return <ErrorText>{err}</ErrorText>;
  if (setups === null) return <Loading />;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-zinc-900">Re-evaluation</h1>
        <p className="text-sm text-zinc-500">
          Review re-evaluation requests, then upload revised SEE marks via
          CSV. The improve-or-hold rule rejects any revised mark strictly
          lower than the original.
        </p>
      </div>

      <Card className="p-3">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Setup">
            <Select
              value={setupId}
              onChange={(e) => {
                setSetupId(e.target.value);
                setOfferingId("");
              }}
            >
              {setups.map((s) => {
                const term = terms.find((t) => t.id === s.academic_term_id);
                return (
                  <option key={s.id} value={s.id}>
                    {term?.code ?? s.id.slice(0, 8)} · {s.state}
                  </option>
                );
              })}
            </Select>
          </Field>
          <Field label="Offering">
            <Select
              value={offeringId}
              onChange={(e) => setOfferingId(e.target.value)}
              disabled={!setupDetail}
            >
              <option value="">— select —</option>
              {(setupDetail?.courses ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.course_code} · {c.section_name}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      </Card>

      <Card className="p-3">
        <p className="text-xs text-zinc-600">
          Paste revised marks CSV — one row per line, USN and revised marks
          separated by comma or tab.
        </p>
        <textarea
          rows={8}
          className="mt-2 w-full rounded border border-zinc-300 bg-white px-2 py-1.5 font-mono text-xs"
          placeholder="1BM23CS001,72&#10;1BM23CS002,68"
          value={csv}
          onChange={(e) => setCsv(e.target.value)}
        />
        <div className="mt-2 flex items-center justify-between text-xs text-zinc-500">
          <span>Parsed: {parsedRows.length} row(s)</span>
          <Button
            onClick={onUpload}
            disabled={
              !offeringId || parsedRows.length === 0 || busy === "upload"
            }
          >
            {busy === "upload" ? "Uploading…" : "Upload"}
          </Button>
        </div>
      </Card>

      {actionErr ? <p className="text-sm text-zinc-700">{actionErr}</p> : null}

      <Card className="overflow-x-auto">
        {requests === null ? (
          <Loading />
        ) : requests.length === 0 ? (
          <p className="px-4 py-6 text-sm text-zinc-500">
            No re-evaluation requests for this offering.
          </p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>USN</Th>
                <Th>Student</Th>
                <Th>Requested</Th>
                <Th>Reason</Th>
                <Th>Original</Th>
                <Th>Revised</Th>
                <Th>Status</Th>
                <Th>Outcome</Th>
              </tr>
            </thead>
            <tbody>
              {requests.map((r) => (
                <tr key={r.id}>
                  <Td className="font-mono text-xs">{r.usn ?? "—"}</Td>
                  <Td>{r.student_name ?? "—"}</Td>
                  <Td className="text-zinc-500">
                    {new Date(r.requested_at).toLocaleDateString()}
                  </Td>
                  <Td className="max-w-[200px] truncate text-xs">
                    {r.reason ?? "—"}
                  </Td>
                  <Td>
                    {r.original_marks !== null
                      ? r.original_marks.toFixed(1)
                      : "—"}
                  </Td>
                  <Td>
                    {r.revised_marks !== null
                      ? r.revised_marks.toFixed(1)
                      : "—"}
                  </Td>
                  <Td>
                    <Badge
                      tone={
                        r.status === "completed"
                          ? "green"
                          : r.status === "rejected"
                            ? "red"
                            : "amber"
                      }
                    >
                      {r.status}
                    </Badge>
                  </Td>
                  <Td>{r.outcome ?? "—"}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
