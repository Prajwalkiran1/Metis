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
  credits: number;
  internal_marks: number | null;
  see_marks: number | null;
  total_percent: number | null;
  grade: string;
  is_pending: boolean;
  is_backlog: boolean;
};

type Version = {
  id: string;
  version_number: number;
  generated_at: string;
  trigger_reason: string;
  pdf_url: string;
};

type Card = {
  id: string;
  academic_term_code: string | null;
  is_finalised: boolean;
  current_version_id: string | null;
  versions: Version[];
  subjects: Subject[];
  sgpa: number | null;
};

const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

function gradeTone(g: string): "green" | "amber" | "red" | "neutral" {
  if (g === "S" || g === "A" || g === "B") return "green";
  if (g === "C" || g === "D") return "amber";
  if (g === "F" || g === "I") return "red";
  return "neutral";
}

export default function StudentGradeCardPage() {
  const [cards, setCards] = useState<Card[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const rows = await api<Card[]>("/workflow/grade-cards");
        setCards(rows);
      } catch (e) {
        setErr(e instanceof ApiError ? e.message : "load failed");
      }
    })();
  }, []);

  if (err) return <ErrorText>{err}</ErrorText>;
  if (cards === null) return <Loading />;

  if (cards.length === 0) {
    return (
      <Card className="p-4 text-sm text-zinc-600">
        <h1 className="text-lg font-semibold text-zinc-900">Grade card</h1>
        <p className="mt-2">
          No grade cards have been finalised for you yet. A card becomes
          visible here once your SEE results land and the term is graded.
        </p>
      </Card>
    );
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-zinc-900">Grade card</h1>
        <p className="text-sm text-zinc-500">
          One card per academic term. Versions update when SEE marks land,
          re-evaluation completes, or makeup is uploaded.
        </p>
      </div>

      {cards.map((c) => (
        <Card key={c.id} className="overflow-x-auto">
          <div className="flex flex-wrap items-center gap-3 border-b border-zinc-200 px-4 py-3 text-sm">
            <Badge tone="neutral">Term {c.academic_term_code ?? "—"}</Badge>
            <Badge tone={c.is_finalised ? "green" : "amber"}>
              {c.is_finalised ? "finalised" : "pending"}
            </Badge>
            {c.sgpa !== null ? (
              <Badge tone="neutral">SGPA {c.sgpa.toFixed(2)}</Badge>
            ) : null}
            {c.current_version_id ? (
              <div className="ml-auto">
                <Button
                  size="sm"
                  onClick={() =>
                    window.open(
                      `${API_URL}/workflow/grade-cards/versions/${c.current_version_id}/pdf`,
                      "_blank",
                    )
                  }
                >
                  Download latest PDF
                </Button>
              </div>
            ) : null}
          </div>
          <Table>
            <thead>
              <tr>
                <Th>Subject</Th>
                <Th>Credits</Th>
                <Th>Internal</Th>
                <Th>SEE</Th>
                <Th>Total %</Th>
                <Th>Grade</Th>
              </tr>
            </thead>
            <tbody>
              {c.subjects.map((s, idx) => (
                <tr key={idx}>
                  <Td>
                    <div className="font-medium">{s.course_code}</div>
                    <div className="text-xs text-zinc-500">
                      {s.course_title}
                    </div>
                  </Td>
                  <Td>{s.credits}</Td>
                  <Td>
                    {s.internal_marks !== null
                      ? s.internal_marks.toFixed(1)
                      : "—"}
                  </Td>
                  <Td>
                    {s.see_marks !== null ? s.see_marks.toFixed(1) : "—"}
                  </Td>
                  <Td>
                    {s.total_percent !== null
                      ? s.total_percent.toFixed(1)
                      : "—"}
                  </Td>
                  <Td>
                    <Badge tone={gradeTone(s.grade)}>{s.grade}</Badge>
                    {s.is_pending ? (
                      <span className="ml-1 text-xs text-amber-700">
                        Pending
                      </span>
                    ) : null}
                    {s.is_backlog ? (
                      <span className="ml-1 text-xs text-red-700">
                        Backlog
                      </span>
                    ) : null}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>

          {c.versions.length > 1 ? (
            <div className="border-t border-zinc-200 px-4 py-3">
              <p className="mb-2 text-xs font-medium text-zinc-600">
                Versions
              </p>
              <ul className="text-xs text-zinc-600">
                {c.versions.map((v) => (
                  <li key={v.id} className="flex items-center gap-2 py-1">
                    <span className="font-medium">v{v.version_number}</span>
                    <span className="text-zinc-500">
                      {new Date(v.generated_at).toLocaleString()}
                    </span>
                    <span className="text-zinc-500">·</span>
                    <Badge tone="neutral">{v.trigger_reason}</Badge>
                    <a
                      href={`${API_URL}/workflow/grade-cards/versions/${v.id}/pdf`}
                      target="_blank"
                      rel="noreferrer"
                      className="ml-auto text-zinc-900 underline"
                    >
                      PDF
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </Card>
      ))}
    </div>
  );
}
