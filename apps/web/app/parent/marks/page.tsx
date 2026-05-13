"use client";

import { useEffect, useMemo, useState } from "react";

import { api, ApiError } from "@/lib/api";
import {
  Badge,
  Card,
  ErrorText,
  Field,
  Loading,
  Select,
  Table,
  Td,
  Th,
} from "@/components/ui";

type AssessmentType = "cie1" | "cie2" | "cie3" | "see" | "assignment" | "lab";

type StudentMarkItem = {
  assessment: {
    id: string;
    course_offering_id: string;
    course_code: string;
    course_title: string;
    type: AssessmentType;
    name: string;
    max_marks: string;
    scheduled_date: string | null;
    state: "draft" | "open" | "locked";
  };
  mark: {
    id: string;
    marks_obtained: string | null;
    is_absent: boolean;
    state: "entered" | "locked";
  } | null;
  class_mean: number | null;
  class_stddev: number | null;
};

type ParentChildView = {
  student: { id: string; name: string; email: string; usn: string | null };
  relationship: "father" | "mother" | "guardian" | "other";
  history: { student_user_id: string; items: StudentMarkItem[] };
};

type ParentMarksView = {
  children: ParentChildView[];
};

export default function ParentMarksPage() {
  const [data, setData] = useState<ParentMarksView | null>(null);
  const [selectedChild, setSelectedChild] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const r = await api<ParentMarksView>("/parent/marks");
        setData(r);
        setSelectedChild(r.children[0]?.student.id ?? null);
      } catch (e) {
        setErr(e instanceof ApiError ? e.message : "failed to load");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const child = useMemo(() => {
    if (!data || !selectedChild) return null;
    return data.children.find((c) => c.student.id === selectedChild) ?? null;
  }, [data, selectedChild]);

  if (loading) return <Loading />;
  if (err) return <ErrorText>{err}</ErrorText>;
  if (!data || data.children.length === 0) {
    return (
      <p className="text-sm text-zinc-500">
        No linked students yet. Contact your child&apos;s college administrator to set up the link.
      </p>
    );
  }

  return (
    <div className="space-y-6">
      <h1 className="text-lg font-semibold text-zinc-900">Marks</h1>

      <Card className="p-4">
        <Field label="Child">
          <Select
            value={selectedChild ?? ""}
            onChange={(e) => setSelectedChild(e.target.value || null)}
          >
            {data.children.map((c) => (
              <option key={c.student.id} value={c.student.id}>
                {c.student.name}
                {c.student.usn ? ` (${c.student.usn})` : ""} · {c.relationship}
              </option>
            ))}
          </Select>
        </Field>
      </Card>

      {child ? (
        <Card className="overflow-hidden">
          <div className="border-b border-zinc-200 bg-zinc-50 px-4 py-2 text-xs text-zinc-600">
            {child.student.name}
            {child.student.usn ? ` · ${child.student.usn}` : ""}
          </div>
          <Table>
            <thead>
              <tr>
                <Th>Course</Th>
                <Th>Type</Th>
                <Th>Name</Th>
                <Th>Date</Th>
                <Th>Marks</Th>
                <Th>Class avg</Th>
                <Th>State</Th>
              </tr>
            </thead>
            <tbody>
              {child.history.items.map((it) => (
                <tr key={it.assessment.id}>
                  <Td className="text-xs">{it.assessment.course_code}</Td>
                  <Td>{it.assessment.type.toUpperCase()}</Td>
                  <Td>{it.assessment.name}</Td>
                  <Td className="text-xs">{it.assessment.scheduled_date ?? "—"}</Td>
                  <Td>
                    {it.mark === null ? (
                      <span className="text-xs text-zinc-400">not entered</span>
                    ) : it.mark.is_absent ? (
                      <Badge tone="amber">absent</Badge>
                    ) : (
                      <span>
                        {it.mark.marks_obtained}
                        <span className="text-xs text-zinc-500">
                          {" / "}
                          {it.assessment.max_marks}
                        </span>
                      </span>
                    )}
                  </Td>
                  <Td className="text-xs">
                    {it.class_mean !== null ? it.class_mean.toFixed(2) : "—"}
                  </Td>
                  <Td>
                    {it.assessment.state === "locked" ? (
                      <Badge tone="red">locked</Badge>
                    ) : (
                      <Badge tone="green">{it.assessment.state}</Badge>
                    )}
                  </Td>
                </tr>
              ))}
              {child.history.items.length === 0 ? (
                <tr>
                  <Td colSpan={7} className="text-center text-sm text-zinc-500">
                    No assessments yet for this child.
                  </Td>
                </tr>
              ) : null}
            </tbody>
          </Table>
        </Card>
      ) : null}
    </div>
  );
}
