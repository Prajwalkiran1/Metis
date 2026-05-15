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
  current_term_setup: {
    id: string;
    academic_term_id: string;
    state: "draft" | "published" | "active" | "archived";
    published_at: string | null;
  } | null;
  electives_summary: {
    under_subscribed_count: number;
    total_options: number;
  } | null;
  placeholder: {
    message: string;
    department_active_offerings: number;
  };
};

type SchemeReadinessOffering = {
  course_offering_id: string;
  course_code: string;
  course_title: string;
  course_type: "theory" | "lab" | "integrated" | "nptel";
  section_name: string;
  is_locked: boolean;
  has_scheme: boolean;
  aat_total_percent: number;
};

type SchemeReadiness = {
  total_offerings: number;
  with_scheme: number;
  locked: number;
  unlocked: number;
  offerings: SchemeReadinessOffering[];
};

export default function HodDashboardPage() {
  const [data, setData] = useState<HodDashboard | null>(null);
  const [readiness, setReadiness] = useState<SchemeReadiness | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [dash, r] = await Promise.all([
          api<HodDashboard>("/hod/dashboard"),
          api<SchemeReadiness>("/hod/scheme-readiness").catch(() => null),
        ]);
        setData(dash);
        setReadiness(r);
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
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-zinc-900">
            Current semester setup
          </h2>
          <a
            href="/hod/semester-setup"
            className="text-xs text-zinc-700 underline"
          >
            Manage
          </a>
        </div>
        {data.current_term_setup ? (
          <div className="mt-2 space-y-1">
            <div className="flex items-center gap-2 text-sm">
              <Badge>{data.current_term_setup.state}</Badge>
              <a
                className="text-zinc-900 underline"
                href={`/hod/semester-setup/${data.current_term_setup.id}`}
              >
                Open
              </a>
            </div>
            {data.current_term_setup.published_at ? (
              <p className="text-xs text-zinc-500">
                Published{" "}
                {new Date(
                  data.current_term_setup.published_at,
                ).toLocaleString()}
              </p>
            ) : (
              <p className="text-xs text-zinc-500">Not yet published.</p>
            )}
          </div>
        ) : (
          <p className="mt-2 text-sm text-zinc-600">
            No setup for this department yet — start one from{" "}
            <a className="underline" href="/hod/semester-setup">
              Semester setup
            </a>
            .
          </p>
        )}
        <p className="mt-4 text-sm text-zinc-600">{data.placeholder.message}</p>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-zinc-500">
          <li>CIE schedule + tasks + internal deadlines — M10d</li>
          <li>Hall tickets + grade cards + SEE/re-eval/makeup — M10e</li>
        </ul>
      </Card>

      {readiness ? (
        <Card className="p-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-zinc-900">
              Scheme readiness
            </h2>
            <a
              href="/hod/scheme-templates"
              className="text-xs text-zinc-700 underline"
            >
              Templates
            </a>
          </div>
          <div className="mt-2 flex flex-wrap gap-3 text-xs text-zinc-700">
            <span>{readiness.total_offerings} offerings</span>
            <span>
              <Badge
                tone={
                  readiness.with_scheme === readiness.total_offerings
                    ? "green"
                    : "amber"
                }
              >
                {readiness.with_scheme} with scheme
              </Badge>
            </span>
            <span>
              <Badge tone="neutral">{readiness.locked} locked</Badge>
            </span>
            <span>
              <Badge
                tone={readiness.unlocked > 0 ? "amber" : "green"}
              >
                {readiness.unlocked} open
              </Badge>
            </span>
          </div>
          {readiness.offerings.some(
            (o) => !o.has_scheme || (!o.is_locked && o.has_scheme),
          ) ? (
            <div className="mt-3 overflow-x-auto">
              <Table>
                <thead>
                  <tr>
                    <Th>Course</Th>
                    <Th>Type</Th>
                    <Th>Section</Th>
                    <Th>AAT %</Th>
                    <Th>State</Th>
                    <Th></Th>
                  </tr>
                </thead>
                <tbody>
                  {readiness.offerings
                    .filter((o) => !o.has_scheme || !o.is_locked)
                    .map((o) => (
                      <tr key={o.course_offering_id}>
                        <Td>
                          <div className="font-medium">{o.course_code}</div>
                          <div className="text-xs text-zinc-500">
                            {o.course_title}
                          </div>
                        </Td>
                        <Td>
                          <Badge tone="neutral">{o.course_type}</Badge>
                        </Td>
                        <Td>{o.section_name}</Td>
                        <Td>
                          {o.has_scheme
                            ? o.aat_total_percent.toFixed(1)
                            : "—"}
                        </Td>
                        <Td>
                          {!o.has_scheme ? (
                            <Badge tone="red">no scheme</Badge>
                          ) : (
                            <Badge tone="amber">open</Badge>
                          )}
                        </Td>
                        <Td>
                          <a
                            href={`/teacher/courses/${o.course_offering_id}/scheme`}
                            className="text-xs text-zinc-900 underline"
                          >
                            Configure →
                          </a>
                        </Td>
                      </tr>
                    ))}
                </tbody>
              </Table>
            </div>
          ) : (
            <p className="mt-3 text-xs text-zinc-500">
              All offerings have locked schemes — marks entry is ready.
            </p>
          )}
        </Card>
      ) : null}

      {data.electives_summary &&
      data.electives_summary.under_subscribed_count > 0 ? (
        <Card className="border-amber-300 bg-amber-50 p-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-amber-900">
              {data.electives_summary.under_subscribed_count} elective option
              {data.electives_summary.under_subscribed_count === 1 ? "" : "s"}{" "}
              under-subscribed
            </h2>
            <a
              href="/hod/electives"
              className="text-sm text-amber-900 underline"
            >
              Review →
            </a>
          </div>
          <p className="mt-1 text-xs text-amber-900">
            Options below their min_enrollment_to_run threshold for the current
            setup. Dissolve them and migrate students to a surviving option.
          </p>
        </Card>
      ) : null}

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
