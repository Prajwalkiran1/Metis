"use client";

import { useCallback, useEffect, useState } from "react";
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

type Term = { id: string; code: string };
type Version = {
  id: string;
  version_number: number;
  generated_at: string;
  pdf_url: string;
};
type HallTicket = {
  id: string;
  student_user_id: string;
  student_name: string | null;
  usn: string | null;
  academic_term_id: string;
  academic_term_code: string | null;
  generated_at: string;
  approved_at: string | null;
  current_version_id: string | null;
  eligible_subject_count: number;
  ineligible_subject_count: number;
  versions: Version[];
};

const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export default function HodHallTicketsPage() {
  const [terms, setTerms] = useState<Term[]>([]);
  const [termId, setTermId] = useState("");
  const [tickets, setTickets] = useState<HallTicket[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const reloadTerms = useCallback(async () => {
    try {
      const t = await api<Term[]>("/academic-terms");
      setTerms(t);
      if (t.length > 0 && !termId) setTermId(t[0].id);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "load failed");
    }
  }, [termId]);

  const reloadTickets = useCallback(async () => {
    if (!termId) {
      setTickets([]);
      return;
    }
    try {
      const rows = await api<HallTicket[]>("/workflow/hall-tickets", {
        query: { academic_term_id: termId },
      });
      setTickets(rows);
      setSelected(new Set());
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "load failed");
    }
  }, [termId]);

  useEffect(() => {
    reloadTerms();
  }, [reloadTerms]);
  useEffect(() => {
    reloadTickets();
  }, [reloadTickets]);

  async function onBatchGenerate() {
    if (!termId) return;
    setBusy("batch");
    setActionErr(null);
    try {
      const out = await api<{
        generated: number;
        regenerated: number;
        skipped: number;
      }>("/workflow/hall-tickets/batch", {
        method: "POST",
        body: { academic_term_id: termId },
      });
      setActionErr(
        `Generated ${out.generated} new, regenerated ${out.regenerated}, skipped ${out.skipped}.`,
      );
      await reloadTickets();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "batch failed");
    } finally {
      setBusy(null);
    }
  }

  async function onApproveSelected() {
    if (selected.size === 0) return;
    setBusy("approve");
    setActionErr(null);
    try {
      const out = await api<{ approved: number }>(
        "/workflow/hall-tickets/approve",
        {
          method: "POST",
          body: { hall_ticket_ids: Array.from(selected) },
        },
      );
      setActionErr(`Approved ${out.approved}.`);
      await reloadTickets();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "approve failed");
    } finally {
      setBusy(null);
    }
  }

  function downloadUrl(versionId: string): string {
    return `${API_URL}/workflow/hall-tickets/versions/${versionId}/pdf`;
  }

  if (err) return <ErrorText>{err}</ErrorText>;
  if (tickets === null) return <Loading />;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-zinc-900">Hall tickets</h1>
        <p className="text-sm text-zinc-500">
          Generate per-student hall tickets with a per-subject eligibility
          snapshot, batch-approve them, and download PDFs.
        </p>
      </div>

      <Card className="p-3">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Term">
            <Select value={termId} onChange={(e) => setTermId(e.target.value)}>
              {terms.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.code}
                </option>
              ))}
            </Select>
          </Field>
          <div className="ml-auto flex gap-2">
            <Button
              variant="secondary"
              onClick={onBatchGenerate}
              disabled={busy === "batch"}
            >
              {busy === "batch" ? "Generating…" : "Batch generate"}
            </Button>
            <Button
              onClick={onApproveSelected}
              disabled={selected.size === 0 || busy === "approve"}
            >
              {busy === "approve" ? "Approving…" : `Approve ${selected.size}`}
            </Button>
          </div>
        </div>
      </Card>

      {actionErr ? <p className="text-sm text-zinc-700">{actionErr}</p> : null}

      <Card className="overflow-x-auto">
        {tickets.length === 0 ? (
          <p className="px-4 py-6 text-sm text-zinc-500">
            No hall tickets yet. Click <em>Batch generate</em> to issue them
            for every student in the term.
          </p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th></Th>
                <Th>USN</Th>
                <Th>Name</Th>
                <Th>Eligible</Th>
                <Th>NA</Th>
                <Th>State</Th>
                <Th>Versions</Th>
                <Th></Th>
              </tr>
            </thead>
            <tbody>
              {tickets.map((t) => (
                <tr key={t.id}>
                  <Td>
                    <input
                      type="checkbox"
                      checked={selected.has(t.id)}
                      onChange={(e) => {
                        const next = new Set(selected);
                        if (e.target.checked) next.add(t.id);
                        else next.delete(t.id);
                        setSelected(next);
                      }}
                      disabled={t.approved_at !== null}
                    />
                  </Td>
                  <Td className="font-mono text-xs">{t.usn ?? "—"}</Td>
                  <Td>{t.student_name ?? "—"}</Td>
                  <Td>
                    <Badge tone="green">{t.eligible_subject_count}</Badge>
                  </Td>
                  <Td>
                    {t.ineligible_subject_count > 0 ? (
                      <Badge tone="red">{t.ineligible_subject_count}</Badge>
                    ) : (
                      "0"
                    )}
                  </Td>
                  <Td>
                    {t.approved_at ? (
                      <Badge tone="green">approved</Badge>
                    ) : (
                      <Badge tone="amber">pending</Badge>
                    )}
                  </Td>
                  <Td>{t.versions.length}</Td>
                  <Td>
                    {t.current_version_id ? (
                      <a
                        href={downloadUrl(t.current_version_id)}
                        className="text-zinc-900 underline"
                        target="_blank"
                        rel="noreferrer"
                      >
                        PDF
                      </a>
                    ) : null}
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
