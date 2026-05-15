"use client";

import { useEffect, useMemo, useState } from "react";

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

type CourseType = "theory" | "lab" | "integrated" | "nptel";

type OptionView = {
  option_id: string;
  course_id: string;
  course_code: string;
  course_title: string;
  course_type: CourseType;
  tentative_teacher_id: string | null;
  tentative_teacher_name: string | null;
  current_enrollment: number;
  min_enrollment_to_run: number;
  max_enrollment: number | null;
  is_dissolved: boolean;
  is_full: boolean;
};

type GroupView = {
  elective_group_id: string;
  name: string;
  description: string | null;
  required_credits: number | null;
  options: OptionView[];
  chosen_option_id: string | null;
};

type WindowReason =
  | "open"
  | "not_yet_open"
  | "closed"
  | "not_published"
  | "no_setup"
  | "window_not_set";

type View = {
  semester_setup_id: string | null;
  academic_term_code: string | null;
  department_code: string | null;
  window: {
    is_open: boolean;
    opens_at: string | null;
    closes_at: string | null;
    reason: WindowReason;
  };
  mandatory_courses: {
    course_offering_id: string;
    course_code: string;
    course_title: string;
    course_type: CourseType;
    section_name: string;
    teacher_name: string | null;
  }[];
  groups: GroupView[];
  migration_alert: { count: number; message: string } | null;
};

function courseTypeTone(t: CourseType): "neutral" | "green" | "amber" | "red" {
  if (t === "integrated") return "green";
  if (t === "lab") return "amber";
  if (t === "nptel") return "red";
  return "neutral";
}

function windowLine(v: View): string {
  const w = v.window;
  if (w.is_open && w.closes_at)
    return `Open — closes ${new Date(w.closes_at).toLocaleString()}`;
  switch (w.reason) {
    case "not_yet_open":
      return w.opens_at
        ? `Opens ${new Date(w.opens_at).toLocaleString()}`
        : "Not yet open";
    case "closed":
      return "Closed";
    case "window_not_set":
      return "Window not set yet";
    case "not_published":
      return "Setup not yet published";
    case "no_setup":
      return "No setup for your term";
    default:
      return "—";
  }
}

export default function StudentRegistrationPage() {
  const [data, setData] = useState<View | null>(null);
  const [err, setErr] = useState<string | null>(null);
  // Local picks: group_id → option_id. Initialised from server choice.
  const [picks, setPicks] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitErr, setSubmitErr] = useState<string | null>(null);
  const [submittedOk, setSubmittedOk] = useState(false);

  async function reload() {
    try {
      const v = await api<View>("/student/registration");
      setData(v);
      const initial: Record<string, string> = {};
      for (const g of v.groups) {
        if (g.chosen_option_id) initial[g.elective_group_id] = g.chosen_option_id;
      }
      setPicks(initial);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "load failed");
    }
  }

  useEffect(() => {
    reload();
  }, []);

  const allChosen = useMemo(() => {
    if (!data) return false;
    if (data.groups.length === 0) return false;
    return data.groups.every((g) => !!picks[g.elective_group_id]);
  }, [data, picks]);

  async function onSubmit() {
    if (!data) return;
    setSubmitting(true);
    setSubmitErr(null);
    setSubmittedOk(false);
    try {
      await api("/student/registration/electives", {
        method: "POST",
        body: {
          choices: data.groups.map((g) => ({
            elective_group_id: g.elective_group_id,
            elective_group_option_id: picks[g.elective_group_id],
          })),
        },
      });
      setSubmittedOk(true);
      await reload();
    } catch (e) {
      setSubmitErr(e instanceof ApiError ? e.message : "submit failed");
    } finally {
      setSubmitting(false);
    }
  }

  if (err) return <ErrorText>{err}</ErrorText>;
  if (!data) return <Loading />;

  const editable = data.window.is_open;

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold text-zinc-900">Registration</h1>
          <p className="text-sm text-zinc-500">
            {data.department_code ?? ""} · {data.academic_term_code ?? ""}
          </p>
        </div>
        <Badge tone={data.window.is_open ? "green" : "amber"}>
          {windowLine(data)}
        </Badge>
      </div>

      {data.migration_alert ? (
        <Card className="border-amber-300 bg-amber-50 p-4">
          <Badge tone="amber">migration</Badge>
          <p className="mt-2 text-sm text-amber-900">
            {data.migration_alert.message}
          </p>
        </Card>
      ) : null}

      <Card className="overflow-x-auto">
        <div className="border-b border-zinc-200 px-4 py-3 text-sm font-semibold text-zinc-900">
          Mandatory courses ({data.mandatory_courses.length})
        </div>
        {data.mandatory_courses.length === 0 ? (
          <p className="px-4 py-6 text-sm text-zinc-500">
            No mandatory courses surfaced yet for your section.
          </p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Course</Th>
                <Th>Type</Th>
                <Th>Section</Th>
                <Th>Teacher</Th>
              </tr>
            </thead>
            <tbody>
              {data.mandatory_courses.map((c) => (
                <tr key={c.course_offering_id}>
                  <Td>
                    <div className="font-medium">{c.course_code}</div>
                    <div className="text-xs text-zinc-500">{c.course_title}</div>
                  </Td>
                  <Td>
                    <Badge tone={courseTypeTone(c.course_type)}>
                      {c.course_type}
                    </Badge>
                  </Td>
                  <Td>{c.section_name}</Td>
                  <Td>{c.teacher_name ?? "—"}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      {data.groups.length === 0 ? (
        <Card className="p-4 text-sm text-zinc-500">
          No elective groups in this setup.
        </Card>
      ) : (
        <div className="space-y-4">
          {data.groups.map((g) => {
            const chosen = picks[g.elective_group_id];
            return (
              <Card key={g.elective_group_id} className="p-4">
                <div className="flex items-baseline justify-between">
                  <h2 className="text-sm font-semibold text-zinc-900">
                    {g.name}{" "}
                    <span className="text-xs font-normal text-zinc-500">
                      — pick one
                    </span>
                  </h2>
                  {g.required_credits != null ? (
                    <span className="text-xs text-zinc-500">
                      {g.required_credits} credits
                    </span>
                  ) : null}
                </div>
                {g.description ? (
                  <p className="mt-1 text-xs text-zinc-500">{g.description}</p>
                ) : null}
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  {g.options.map((o) => {
                    const isPicked = chosen === o.option_id;
                    const disabled =
                      !editable ||
                      o.is_dissolved ||
                      (o.is_full && !isPicked);
                    return (
                      <button
                        type="button"
                        key={o.option_id}
                        disabled={disabled}
                        onClick={() =>
                          setPicks((p) => ({
                            ...p,
                            [g.elective_group_id]: o.option_id,
                          }))
                        }
                        className={
                          "rounded border p-3 text-left text-sm transition" +
                          (isPicked
                            ? " border-zinc-900 bg-zinc-50"
                            : " border-zinc-200 bg-white") +
                          (disabled
                            ? " cursor-not-allowed opacity-60"
                            : " hover:border-zinc-400")
                        }
                      >
                        <div className="flex items-center justify-between">
                          <div className="font-medium">{o.course_code}</div>
                          <Badge tone={courseTypeTone(o.course_type)}>
                            {o.course_type}
                          </Badge>
                        </div>
                        <div className="text-xs text-zinc-500">
                          {o.course_title}
                        </div>
                        <div className="mt-2 text-xs text-zinc-600">
                          {o.tentative_teacher_name ?? "Teacher TBD"}
                        </div>
                        <div className="mt-1 flex flex-wrap gap-2 text-[11px] text-zinc-600">
                          <span>
                            {o.current_enrollment}
                            {o.max_enrollment != null
                              ? ` / ${o.max_enrollment}`
                              : ""}{" "}
                            enrolled
                          </span>
                          {o.current_enrollment < o.min_enrollment_to_run ? (
                            <Badge tone="amber">
                              below min ({o.min_enrollment_to_run})
                            </Badge>
                          ) : null}
                          {o.is_full ? <Badge tone="red">full</Badge> : null}
                          {o.is_dissolved ? (
                            <Badge tone="red">dissolved</Badge>
                          ) : null}
                        </div>
                      </button>
                    );
                  })}
                </div>
              </Card>
            );
          })}
        </div>
      )}

      <div className="flex items-center gap-3">
        <Button
          onClick={onSubmit}
          disabled={!editable || !allChosen || submitting}
          title={
            !editable
              ? "Registration window is closed"
              : !allChosen
                ? "Pick one option per group"
                : undefined
          }
        >
          {submitting
            ? "Submitting…"
            : data.groups.some((g) => g.chosen_option_id)
              ? "Update registration"
              : "Submit registration"}
        </Button>
        {submittedOk ? (
          <span className="text-sm text-green-700">Registration saved.</span>
        ) : null}
        {submitErr ? <ErrorText>{submitErr}</ErrorText> : null}
      </div>
    </div>
  );
}
