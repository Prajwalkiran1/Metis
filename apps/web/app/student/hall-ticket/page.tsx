"use client";

import { useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  ErrorText,
  Loading,
  Table,
  Td,
  Th,
} from "@/components/ui";

type Subject = {
  course_code: string;
  course_title: string;
  course_type: string;
  attendance_percent: number;
  cie_percent: number | null;
  overall_eligible: boolean;
  reason: string | null;
};

type Version = {
  id: string;
  version_number: number;
  generated_at: string;
  pdf_url: string;
  eligibility_snapshot: {
    subjects: Subject[];
  };
};

type HallTicket = {
  id: string;
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

export default function StudentHallTicketPage() {
  const [ticket, setTicket] = useState<HallTicket | null | false>(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const t = await api<HallTicket | null>("/workflow/hall-tickets/me");
        setTicket(t);
      } catch (e) {
        setErr(e instanceof ApiError ? e.message : "load failed");
      }
    })();
  }, []);

  if (err) return <ErrorText>{err}</ErrorText>;
  if (ticket === false) return <Loading />;

  if (ticket === null) {
    return (
      <Card className="p-4 text-sm text-zinc-600">
        <h1 className="text-lg font-semibold text-zinc-900">Hall ticket</h1>
        <p className="mt-2">
          Your HOD hasn't generated a hall ticket for the current term yet.
        </p>
      </Card>
    );
  }

  const latest = ticket.versions[0];

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-zinc-900">Hall ticket</h1>
        <p className="text-sm text-zinc-500">
          Subjects marked NA mean you're ineligible for that SEE. Download the
          PDF and bring a printed copy to the exam hall.
        </p>
      </div>

      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <Badge tone="neutral">
            Term {ticket.academic_term_code ?? "—"}
          </Badge>
          <Badge tone={ticket.approved_at ? "green" : "amber"}>
            {ticket.approved_at ? "approved" : "pending approval"}
          </Badge>
          <Badge tone="green">{ticket.eligible_subject_count} eligible</Badge>
          {ticket.ineligible_subject_count > 0 ? (
            <Badge tone="red">{ticket.ineligible_subject_count} NA</Badge>
          ) : null}
          <span className="ml-auto text-xs text-zinc-500">
            Generated {new Date(ticket.generated_at).toLocaleString()}
          </span>
        </div>
        {ticket.current_version_id ? (
          <div className="mt-3">
            <Button
              onClick={() =>
                window.open(
                  `${API_URL}/workflow/hall-tickets/versions/${ticket.current_version_id}/pdf`,
                  "_blank",
                )
              }
            >
              Download PDF
            </Button>
          </div>
        ) : null}
      </Card>

      {latest ? (
        <Card className="overflow-x-auto">
          <div className="border-b border-zinc-200 px-4 py-3 text-sm font-semibold text-zinc-900">
            Per-subject eligibility (v{latest.version_number})
          </div>
          <Table>
            <thead>
              <tr>
                <Th>Subject</Th>
                <Th>Type</Th>
                <Th>Att %</Th>
                <Th>CIE %</Th>
                <Th>Status</Th>
                <Th>Reason</Th>
              </tr>
            </thead>
            <tbody>
              {latest.eligibility_snapshot.subjects.map((s, idx) => (
                <tr key={idx}>
                  <Td>
                    <div className="font-medium">{s.course_code}</div>
                    <div className="text-xs text-zinc-500">
                      {s.course_title}
                    </div>
                  </Td>
                  <Td>
                    <Badge tone="neutral">{s.course_type}</Badge>
                  </Td>
                  <Td>{s.attendance_percent.toFixed(1)}</Td>
                  <Td>
                    {s.cie_percent !== null
                      ? s.cie_percent.toFixed(1)
                      : "—"}
                  </Td>
                  <Td>
                    {s.overall_eligible ? (
                      <Badge tone="green">eligible</Badge>
                    ) : (
                      <Badge tone="red">NA</Badge>
                    )}
                  </Td>
                  <Td className="text-xs text-zinc-600">{s.reason ?? "—"}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      ) : null}

      {ticket.versions.length > 1 ? (
        <Card className="overflow-x-auto">
          <div className="border-b border-zinc-200 px-4 py-3 text-sm font-semibold text-zinc-900">
            Version history
          </div>
          <Table>
            <thead>
              <tr>
                <Th>Version</Th>
                <Th>Generated</Th>
                <Th></Th>
              </tr>
            </thead>
            <tbody>
              {ticket.versions.map((v) => (
                <tr key={v.id}>
                  <Td>v{v.version_number}</Td>
                  <Td className="text-zinc-500">
                    {new Date(v.generated_at).toLocaleString()}
                  </Td>
                  <Td>
                    <a
                      href={`${API_URL}/workflow/hall-tickets/versions/${v.id}/pdf`}
                      target="_blank"
                      rel="noreferrer"
                      className="text-zinc-900 underline"
                    >
                      PDF
                    </a>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      ) : null}
    </div>
  );
}
