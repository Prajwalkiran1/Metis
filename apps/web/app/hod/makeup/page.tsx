"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, api } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  ErrorText,
  Field,
  Input,
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

type SEEResult = {
  id: string;
  enrollment_id: number;
  usn: string | null;
  student_name: string | null;
  kind: "original" | "re_evaluation" | "makeup";
  marks_obtained: number | null;
  max_marks: number;
  is_current: boolean;
};

export default function HodMakeupPage() {
  const [setups, setSetups] = useState<SetupList[] | null>(null);
  const [terms, setTerms] = useState<Term[]>([]);
  const [setupId, setSetupId] = useState("");
  const [setupDetail, setSetupDetail] = useState<SetupDetail | null>(null);
  const [offeringId, setOfferingId] = useState("");
  const [results, setResults] = useState<SEEResult[] | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [csv, setCsv] = useState("");
  const [maxMarks, setMaxMarks] = useState("100");
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

  const reloadResults = useCallback(async () => {
    if (!offeringId) {
      setResults([]);
      return;
    }
    try {
      const r = await api<SEEResult[]>("/workflow/see-results", {
        query: { course_offering_id: offeringId },
      });
      setResults(r);
      setSelected(new Set());
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
    reloadResults();
  }, [reloadResults]);

  // Show students whose CURRENT SEE row is original AND marks < 40% (failed).
  const failedStudents = useMemo(() => {
    if (!results) return [];
    return results.filter(
      (r) =>
        r.is_current &&
        r.kind === "original" &&
        r.marks_obtained !== null &&
        (r.marks_obtained / r.max_marks) * 100 < 40,
    );
  }, [results]);

  const parsedRows = useMemo(() => {
    return csv
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line && !line.startsWith("#"))
      .map((line) => {
        const [usn, marks] = line.split(/[,\t]/).map((s) => s.trim());
        return { usn, marks_obtained: Number(marks) };
      })
      .filter((r) => r.usn && !Number.isNaN(r.marks_obtained));
  }, [csv]);

  async function onAuthorize() {
    if (!offeringId || selected.size === 0) return;
    setBusy("authorize");
    setActionErr(null);
    try {
      const out = await api<{ authorised: number }>(
        "/workflow/makeup/authorize",
        {
          method: "POST",
          body: {
            course_offering_id: offeringId,
            enrollment_ids: Array.from(selected),
          },
        },
      );
      setActionErr(`Authorised ${out.authorised} student(s).`);
      await reloadResults();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "authorize failed");
    } finally {
      setBusy(null);
    }
  }

  async function onUpload() {
    if (!offeringId || parsedRows.length === 0) return;
    setBusy("upload");
    setActionErr(null);
    try {
      const out = await api<{
        processed: number;
        skipped: { usn: string; reason: string }[];
      }>("/workflow/makeup/upload", {
        method: "POST",
        body: {
          course_offering_id: offeringId,
          max_marks: Number(maxMarks),
          rows: parsedRows,
        },
      });
      setActionErr(
        `Processed ${out.processed}, skipped ${out.skipped.length}.`,
      );
      setCsv("");
      await reloadResults();
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
        <h1 className="text-lg font-semibold text-zinc-900">Makeup exam</h1>
        <p className="text-sm text-zinc-500">
          Authorise students for the makeup exam, then upload makeup marks
          via CSV. The makeup row supersedes the current SEE row.
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

      {actionErr ? <p className="text-sm text-zinc-700">{actionErr}</p> : null}

      <Card className="overflow-x-auto">
        <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-3">
          <h2 className="text-sm font-semibold text-zinc-900">
            Authorise students ({failedStudents.length} failed below 40%)
          </h2>
          <Button
            size="sm"
            onClick={onAuthorize}
            disabled={selected.size === 0 || busy === "authorize"}
          >
            {busy === "authorize" ? "…" : `Authorise ${selected.size}`}
          </Button>
        </div>
        {failedStudents.length === 0 ? (
          <p className="px-4 py-6 text-sm text-zinc-500">
            Nobody failed the SEE in this offering yet (or no SEE rows
            uploaded). Authorisation is shown only for students with original
            SEE marks below 40%.
          </p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th></Th>
                <Th>USN</Th>
                <Th>Student</Th>
                <Th>Marks</Th>
                <Th>Percent</Th>
              </tr>
            </thead>
            <tbody>
              {failedStudents.map((r) => {
                const pct = r.marks_obtained
                  ? (r.marks_obtained / r.max_marks) * 100
                  : 0;
                return (
                  <tr key={r.id}>
                    <Td>
                      <input
                        type="checkbox"
                        checked={selected.has(r.enrollment_id)}
                        onChange={(e) => {
                          const next = new Set(selected);
                          if (e.target.checked) next.add(r.enrollment_id);
                          else next.delete(r.enrollment_id);
                          setSelected(next);
                        }}
                      />
                    </Td>
                    <Td className="font-mono text-xs">{r.usn ?? "—"}</Td>
                    <Td>{r.student_name ?? "—"}</Td>
                    <Td>{r.marks_obtained?.toFixed(1) ?? "—"}</Td>
                    <Td>
                      <Badge tone="red">{pct.toFixed(1)}%</Badge>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}
      </Card>

      <Card className="p-3">
        <p className="text-xs text-zinc-600">
          Upload makeup marks (USN, marks). Only previously-authorised students
          will be processed.
        </p>
        <div className="mt-2 flex gap-2">
          <Field label="Max marks">
            <Input
              type="number"
              value={maxMarks}
              onChange={(e) => setMaxMarks(e.target.value)}
              className="max-w-[100px]"
            />
          </Field>
        </div>
        <textarea
          rows={6}
          className="mt-2 w-full rounded border border-zinc-300 bg-white px-2 py-1.5 font-mono text-xs"
          placeholder="1BM23CS001,52"
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
            {busy === "upload" ? "Uploading…" : "Upload marks"}
          </Button>
        </div>
      </Card>
    </div>
  );
}
