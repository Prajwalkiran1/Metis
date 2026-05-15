"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { ApiError, api } from "@/lib/api";
import { Badge, Card, ErrorText, Loading } from "@/components/ui";

type WindowReason =
  | "open"
  | "not_yet_open"
  | "closed"
  | "not_published"
  | "no_setup"
  | "window_not_set";

type StudentRegistrationView = {
  semester_setup_id: string | null;
  academic_term_code: string | null;
  department_code: string | null;
  window: {
    is_open: boolean;
    opens_at: string | null;
    closes_at: string | null;
    reason: WindowReason;
  };
  mandatory_courses: { course_code: string; course_title: string }[];
  groups: {
    elective_group_id: string;
    name: string;
    preferences: { option_id: string; rank: number }[];
  }[];
  migration_alert: { count: number; message: string } | null;
  intervention_alert: { count: number; message: string } | null;
};

function windowLine(v: StudentRegistrationView): string {
  const w = v.window;
  if (w.is_open && w.closes_at) {
    return `Registration is open — closes ${new Date(w.closes_at).toLocaleString()}`;
  }
  switch (w.reason) {
    case "not_yet_open":
      return w.opens_at
        ? `Registration opens ${new Date(w.opens_at).toLocaleString()}`
        : "Registration not yet open";
    case "closed":
      return "Registration is closed";
    case "window_not_set":
      return "Your department hasn't set the registration window yet";
    case "not_published":
      return "Your semester setup hasn't been published yet";
    case "no_setup":
      return "No semester setup found for your department";
    default:
      return "—";
  }
}

export default function StudentDashboardPage() {
  const [data, setData] = useState<StudentRegistrationView | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        setData(await api<StudentRegistrationView>("/student/registration"));
      } catch (e) {
        setErr(e instanceof ApiError ? e.message : "load failed");
      }
    })();
  }, []);

  if (err) return <ErrorText>{err}</ErrorText>;
  if (!data) return <Loading />;

  const groupsWithChoice = data.groups.filter(
    (g) => g.preferences.length > 0,
  );
  const hasRegistered = groupsWithChoice.length > 0;
  const allChosen =
    data.groups.length > 0 &&
    groupsWithChoice.length === data.groups.length;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-zinc-900">Dashboard</h1>
        <p className="text-sm text-zinc-500">
          {data.department_code
            ? `${data.department_code} · ${data.academic_term_code ?? ""}`
            : ""}
        </p>
      </div>

      {data.migration_alert ? (
        <Card className="border-amber-300 bg-amber-50 p-4">
          <div className="flex items-start gap-3">
            <Badge tone="amber">migration</Badge>
            <div>
              <p className="text-sm font-medium text-amber-900">
                Your elective was changed
              </p>
              <p className="text-sm text-amber-800">
                {data.migration_alert.message}
              </p>
              <Link
                href="/student/registration"
                className="mt-1 inline-block text-sm text-amber-900 underline"
              >
                View registration
              </Link>
            </div>
          </div>
        </Card>
      ) : null}

      {data.intervention_alert ? (
        <Card className="border-red-300 bg-red-50 p-4">
          <div className="flex items-start gap-3">
            <Badge tone="red">needs HOD attention</Badge>
            <div>
              <p className="text-sm font-medium text-red-900">
                An elective slot needs HOD attention
              </p>
              <p className="text-sm text-red-800">
                {data.intervention_alert.message}
              </p>
              <Link
                href="/student/registration"
                className="mt-1 inline-block text-sm text-red-900 underline"
              >
                View registration
              </Link>
            </div>
          </div>
        </Card>
      ) : null}

      <Card className="p-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-zinc-900">
            Course registration
          </h2>
          <Badge
            tone={
              data.window.is_open ? "green" : hasRegistered ? "neutral" : "amber"
            }
          >
            {data.window.reason}
          </Badge>
        </div>
        <p className="mt-1 text-sm text-zinc-600">{windowLine(data)}</p>
        {data.window.is_open && !allChosen ? (
          <div className="mt-3 rounded border border-amber-200 bg-amber-50 p-3">
            <p className="text-sm text-amber-900">
              Registration is open — pick your electives.
            </p>
            <Link
              href="/student/registration"
              className="text-sm text-amber-900 underline"
            >
              Go to registration →
            </Link>
          </div>
        ) : hasRegistered ? (
          <div className="mt-3 text-sm text-zinc-700">
            You have chosen {groupsWithChoice.length} of {data.groups.length}{" "}
            electives.{" "}
            <Link
              href="/student/registration"
              className="text-zinc-900 underline"
            >
              View registration
            </Link>
          </div>
        ) : null}
      </Card>

      <Card className="p-4">
        <h2 className="text-sm font-semibold text-zinc-900">
          Mandatory courses ({data.mandatory_courses.length})
        </h2>
        {data.mandatory_courses.length === 0 ? (
          <p className="mt-2 text-sm text-zinc-500">No mandatory courses surfaced yet.</p>
        ) : (
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-zinc-700">
            {data.mandatory_courses.slice(0, 6).map((c) => (
              <li key={c.course_code}>
                <span className="font-medium">{c.course_code}</span> —{" "}
                {c.course_title}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
