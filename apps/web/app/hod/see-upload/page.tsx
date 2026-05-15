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

type SetupList = {
  id: string;
  state: string;
  academic_term_id: string;
};

type CourseAssignment = {
  id: string;
  course_code: string;
  course_title: string;
  course_type: string;
  section_name: string;
};

type SetupDetail = { id: string; courses: CourseAssignment[] };

type SEEResult = {
  id: string;
  enrollment_id: number;
  usn: string | null;
  student_name: string | null;
  kind: "original" | "re_evaluation" | "makeup";
  marks_obtained: number | null;
  max_marks: number;
  uploaded_at: string | null;
  is_current: boolean;
};

type Term = { id: string; code: string };

export default function HodSeeUploadPage() {
  const [setups, setSetups] = useState<SetupList[] | null>(null);
  const [terms, setTerms] = useState<Term[]>([]);
  const [setupId, setSetupId] = useState("");
  const [setupDetail, setSetupDetail] = useState<SetupDetail | null>(null);
  const [offeringId, setOfferingId] = useState("");
  const [results, setResults] = useState<SEEResult[] | null>(null);
  const [csv, setCsv] = useState("");
  const [maxMarks, setMaxMarks] = useState("100");
  const [err, setErr] = useState<string | null>(null);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const reloadSetups = useCallback(async () => {
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
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "load failed");
    }
  }, [offeringId]);

  useEffect(() => {
    reloadSetups();
  }, [reloadSetups]);
  useEffect(() => {
    reloadDetail();
  }, [reloadDetail]);
  useEffect(() => {
    reloadResults();
  }, [reloadResults]);

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

  async function onUpload() {
    if (!offeringId || parsedRows.length === 0) return;
    setBusy("upload");
    setActionErr(null);
    try {
      const out = await api<{
        inserted: number;
        skipped: { usn: string; reason: string }[];
      }>("/workflow/see-results/upload", {
        method: "POST",
        body: {
          course_offering_id: offeringId,
          max_marks: Number(maxMarks),
          rows: parsedRows,
        },
      });
      setActionErr(
        `Inserted ${out.inserted}, skipped ${out.skipped.length}.${out.skipped.length ? " Reasons: " + out.skipped.map((s) => `${s.usn}=${s.reason}`).join(", ") : ""}`,
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
        <h1 className="text-lg font-semibold text-zinc-900">SEE upload</h1>
        <p className="text-sm text-zinc-500">
          Upload SEE results via CSV (one row per student: USN, marks). Each
          upload supersedes the previous current row; a downstream grade card
          regenerate is triggered automatically.
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
          <Field label="Max marks">
            <Input
              type="number"
              value={maxMarks}
              onChange={(e) => setMaxMarks(e.target.value)}
              className="max-w-[100px]"
            />
          </Field>
        </div>
      </Card>

      <Card className="p-3">
        <p className="text-xs text-zinc-600">
          Paste CSV — one row per line, USN and marks separated by comma or
          tab. Lines starting with # are ignored.
        </p>
        <textarea
          rows={8}
          className="mt-2 w-full rounded border border-zinc-300 bg-white px-2 py-1.5 font-mono text-xs"
          placeholder="1BM23CS001,75&#10;1BM23CS002,62"
          value={csv}
          onChange={(e) => setCsv(e.target.value)}
        />
        <div className="mt-2 flex items-center justify-between text-xs text-zinc-500">
          <span>Parsed: {parsedRows.length} row(s)</span>
          <Button
            onClick={onUpload}
            disabled={!offeringId || parsedRows.length === 0 || busy === "upload"}
          >
            {busy === "upload" ? "Uploading…" : "Upload"}
          </Button>
        </div>
      </Card>

      {actionErr ? <p className="text-sm text-zinc-700">{actionErr}</p> : null}

      <Card className="overflow-x-auto">
        {results === null ? (
          <Loading />
        ) : results.length === 0 ? (
          <p className="px-4 py-6 text-sm text-zinc-500">
            No SEE results uploaded yet for this offering.
          </p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>USN</Th>
                <Th>Student</Th>
                <Th>Kind</Th>
                <Th>Marks</Th>
                <Th>Current</Th>
                <Th>Uploaded</Th>
              </tr>
            </thead>
            <tbody>
              {results.map((r) => (
                <tr key={r.id}>
                  <Td className="font-mono text-xs">{r.usn ?? "—"}</Td>
                  <Td>{r.student_name ?? "—"}</Td>
                  <Td>
                    <Badge tone="neutral">{r.kind}</Badge>
                  </Td>
                  <Td>
                    {r.marks_obtained === null
                      ? "—"
                      : `${r.marks_obtained.toFixed(1)} / ${r.max_marks.toFixed(0)}`}
                  </Td>
                  <Td>
                    {r.is_current ? (
                      <Badge tone="green">current</Badge>
                    ) : (
                      <Badge tone="neutral">history</Badge>
                    )}
                  </Td>
                  <Td className="text-zinc-500">
                    {r.uploaded_at
                      ? new Date(r.uploaded_at).toLocaleString()
                      : "—"}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
