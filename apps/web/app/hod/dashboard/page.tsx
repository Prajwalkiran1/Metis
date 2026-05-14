"use client";

import { useEffect, useState } from "react";

import { ApiError, api } from "@/lib/api";
import { Badge, Card, ErrorText, Loading, Table, Td, Th } from "@/components/ui";

type TeachingOffering = {
  id: string;
  course_code: string;
  course_title: string;
  section_name: string;
  academic_term: string;
};

type HodDashboard = {
  department: { id: string; code: string; name: string };
  teaching_offerings: TeachingOffering[];
  placeholder: {
    message: string;
    department_active_offerings: number;
  };
};

export default function HodDashboardPage() {
  const [data, setData] = useState<HodDashboard | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        setData(await api<HodDashboard>("/hod/dashboard"));
      } catch (e) {
        setErr(e instanceof ApiError ? e.message : "load failed");
      }
    })();
  }, []);

  if (err) return <ErrorText>{err}</ErrorText>;
  if (!data) return <Loading />;

  const offerings = data.teaching_offerings;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-zinc-900">
          Welcome — HOD of {data.department.name}
        </h1>
        <p className="text-sm text-zinc-500">
          Department code: <code>{data.department.code}</code> ·{" "}
          {data.placeholder.department_active_offerings} active offerings this
          term.
        </p>
      </div>

      <Card className="p-4">
        <h2 className="mb-2 text-sm font-semibold text-zinc-900">
          Department overview
        </h2>
        <p className="text-sm text-zinc-600">
          {data.placeholder.message}
        </p>
        <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-zinc-500">
          <li>Semester setup draft &amp; publish flow — M10a</li>
          <li>Elective registration + dissolution + cascade — M10b</li>
          <li>Lab batches + assessment scheme picker — M10c</li>
          <li>CIE schedule + tasks + internal deadlines — M10d</li>
          <li>Hall tickets + grade cards + SEE/re-eval/makeup — M10e</li>
        </ul>
      </Card>

      <Card className="overflow-x-auto">
        <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-3">
          <h2 className="text-sm font-semibold text-zinc-900">
            My teaching offerings
          </h2>
          <Badge>{offerings.length}</Badge>
        </div>
        {offerings.length === 0 ? (
          <p className="px-4 py-6 text-sm text-zinc-500">
            You are not teaching any active offerings this term.
          </p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Course</Th>
                <Th>Section</Th>
                <Th>Term</Th>
              </tr>
            </thead>
            <tbody>
              {offerings.map((o) => (
                <tr key={o.id}>
                  <Td>
                    <div className="font-medium">{o.course_code}</div>
                    <div className="text-xs text-zinc-500">
                      {o.course_title}
                    </div>
                  </Td>
                  <Td>{o.section_name}</Td>
                  <Td className="text-zinc-600">{o.academic_term}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
