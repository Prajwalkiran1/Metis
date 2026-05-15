"use client";

import { useEffect, useMemo, useState } from "react";

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

type PreferenceEntry = { option_id: string; rank: number };

type GroupView = {
  elective_group_id: string;
  name: string;
  description: string | null;
  required_credits: number | null;
  options: OptionView[];
  preferences: PreferenceEntry[];
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
  intervention_alert: { count: number; message: string } | null;
};

type CommittedEntry = {
  course_id: string;
  course_code: string;
  course_title: string;
  course_type: CourseType;
  status: "enrolled" | "migrated_from" | "needs_intervention";
  migrated_from_option_label: string | null;
  offering_id: string | null;
  elective_group_name: string | null;
};

type CommittedView = {
  semester_setup_id: string | null;
  academic_term_code: string | null;
  department_code: string | null;
  courses: CommittedEntry[];
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

// Local pick state: groupId → [rank1, rank2, rank3] where each slot is an
// option_id (or null = unset). Rank-1 (slot 0) is required.
type Picks = Record<string, (string | null)[]>;

export default function StudentRegistrationPage() {
  const [data, setData] = useState<View | null>(null);
  const [committed, setCommitted] = useState<CommittedView | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [picks, setPicks] = useState<Picks>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitErr, setSubmitErr] = useState<string | null>(null);
  const [submittedOk, setSubmittedOk] = useState(false);

  async function reload() {
    try {
      const v = await api<View>("/student/registration");
      setData(v);
      // Seed picks from server state. Pad to 3 slots so the UI is stable.
      const initial: Picks = {};
      for (const g of v.groups) {
        const slots: (string | null)[] = [null, null, null];
        for (const p of g.preferences) {
          if (p.rank >= 1 && p.rank <= 3) slots[p.rank - 1] = p.option_id;
        }
        initial[g.elective_group_id] = slots;
      }
      setPicks(initial);

      // Closed state — also fetch the unified committed view.
      if (!v.window.is_open) {
        try {
          const c = await api<CommittedView>("/student/registration/committed");
          setCommitted(c);
        } catch {
          setCommitted(null);
        }
      } else {
        setCommitted(null);
      }
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "load failed");
    }
  }

  useEffect(() => {
    reload();
  }, []);

  const allRank1Set = useMemo(() => {
    if (!data) return false;
    if (data.groups.length === 0) return true;
    return data.groups.every(
      (g) => !!picks[g.elective_group_id]?.[0],
    );
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
          choices: data.groups.map((g) => {
            const slots = picks[g.elective_group_id] ?? [null, null, null];
            const ranked = slots.filter((s): s is string => !!s);
            return {
              elective_group_id: g.elective_group_id,
              ranked_option_ids: ranked,
            };
          }),
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

  function setRank(eg_id: string, rank_idx: number, value: string | null) {
    setPicks((prev) => {
      const cur = prev[eg_id] ?? [null, null, null];
      const next = cur.slice() as (string | null)[];
      next[rank_idx] = value;
      // Dedupe within the group — if the same option is set elsewhere, clear it.
      for (let i = 0; i < next.length; i++) {
        if (i !== rank_idx && next[i] === value && value !== null) {
          next[i] = null;
        }
      }
      return { ...prev, [eg_id]: next };
    });
  }

  if (err) return <ErrorText>{err}</ErrorText>;
  if (!data) return <Loading />;

  const showClosedView = !data.window.is_open && committed !== null;

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

      {data.intervention_alert ? (
        <Card className="border-red-300 bg-red-50 p-4">
          <Badge tone="red">needs HOD attention</Badge>
          <p className="mt-2 text-sm text-red-900">
            {data.intervention_alert.message}
          </p>
        </Card>
      ) : null}

      {showClosedView ? (
        <ClosedView committed={committed!} />
      ) : (
        <OpenView
          data={data}
          picks={picks}
          setRank={setRank}
          submitting={submitting}
          submittedOk={submittedOk}
          submitErr={submitErr}
          onSubmit={onSubmit}
          allRank1Set={allRank1Set}
          editable={data.window.is_open}
        />
      )}
    </div>
  );
}

// ── Closed state — unified locked-in courses table (B6 + B7) ───────────────
function ClosedView({ committed }: { committed: CommittedView }) {
  return (
    <Card className="overflow-x-auto">
      <div className="border-b border-zinc-200 px-4 py-3 text-sm font-semibold text-zinc-900">
        My registered courses ({committed.courses.length})
      </div>
      {committed.courses.length === 0 ? (
        <p className="px-4 py-6 text-sm text-zinc-500">
          Nothing registered yet for this term.
        </p>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>Course</Th>
              <Th>Type</Th>
              <Th>Source</Th>
              <Th>Status</Th>
            </tr>
          </thead>
          <tbody>
            {committed.courses.map((c) => (
              <tr key={c.course_id + ":" + c.status}>
                <Td>
                  <div className="font-medium">{c.course_code}</div>
                  <div className="text-xs text-zinc-500">{c.course_title}</div>
                  {c.elective_group_name ? (
                    <div className="text-xs text-zinc-400">
                      Elective · {c.elective_group_name}
                    </div>
                  ) : null}
                </Td>
                <Td>
                  <Badge tone={courseTypeTone(c.course_type)}>
                    {c.course_type}
                  </Badge>
                </Td>
                <Td>
                  {c.status === "migrated_from" &&
                  c.migrated_from_option_label ? (
                    <span className="text-xs text-zinc-600">
                      from {c.migrated_from_option_label}
                    </span>
                  ) : (
                    "—"
                  )}
                </Td>
                <Td>
                  {c.status === "enrolled" ? (
                    <Badge tone="green">enrolled</Badge>
                  ) : c.status === "migrated_from" ? (
                    <Badge tone="amber">migrated</Badge>
                  ) : (
                    <Badge tone="red">needs HOD attention</Badge>
                  )}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  );
}

// ── Open state — ranked picker (3 dropdowns per group) ─────────────────────
function OpenView({
  data,
  picks,
  setRank,
  submitting,
  submittedOk,
  submitErr,
  onSubmit,
  allRank1Set,
  editable,
}: {
  data: View;
  picks: Picks;
  setRank: (eg_id: string, rank_idx: number, value: string | null) => void;
  submitting: boolean;
  submittedOk: boolean;
  submitErr: string | null;
  onSubmit: () => void;
  allRank1Set: boolean;
  editable: boolean;
}) {
  return (
    <>
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
          {data.groups.map((g) => (
            <GroupPicker
              key={g.elective_group_id}
              group={g}
              slots={picks[g.elective_group_id] ?? [null, null, null]}
              onSlot={(idx, val) => setRank(g.elective_group_id, idx, val)}
              editable={editable}
            />
          ))}
        </div>
      )}

      <div className="flex items-center gap-3">
        <Button
          onClick={onSubmit}
          disabled={!editable || !allRank1Set || submitting}
          title={
            !editable
              ? "Registration window is closed"
              : !allRank1Set
                ? "Set a 1st choice for every elective group"
                : undefined
          }
        >
          {submitting
            ? "Submitting…"
            : data.groups.some((g) => g.preferences.length > 0)
              ? "Update preferences"
              : "Submit preferences"}
        </Button>
        {submittedOk ? (
          <span className="text-sm text-green-700">Preferences saved.</span>
        ) : null}
        {submitErr ? <ErrorText>{submitErr}</ErrorText> : null}
      </div>
    </>
  );
}

function GroupPicker({
  group,
  slots,
  onSlot,
  editable,
}: {
  group: GroupView;
  slots: (string | null)[];
  onSlot: (idx: number, val: string | null) => void;
  editable: boolean;
}) {
  // Options that aren't dissolved are pickable at any rank. Dissolved are
  // excluded from the dropdowns entirely.
  const pickable = group.options.filter((o) => !o.is_dissolved);

  function optionsForSlot(slotIdx: number) {
    const otherPicked = slots
      .map((s, i) => (i !== slotIdx ? s : null))
      .filter((s): s is string => !!s);
    return pickable.filter((o) => !otherPicked.includes(o.option_id));
  }

  return (
    <Card className="p-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-semibold text-zinc-900">
          {group.name}{" "}
          <span className="text-xs font-normal text-zinc-500">
            — rank your choices
          </span>
        </h2>
        {group.required_credits != null ? (
          <span className="text-xs text-zinc-500">
            {group.required_credits} credits
          </span>
        ) : null}
      </div>
      {group.description ? (
        <p className="mt-1 text-xs text-zinc-500">{group.description}</p>
      ) : null}

      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        {[0, 1, 2].map((idx) => {
          const label =
            idx === 0
              ? "1st choice (required)"
              : idx === 1
                ? "2nd choice (optional)"
                : "3rd choice (optional)";
          const available = optionsForSlot(idx);
          const current = slots[idx] ?? "";
          return (
            <Field key={idx} label={label}>
              <Select
                value={current}
                disabled={!editable}
                onChange={(e) => onSlot(idx, e.target.value || null)}
              >
                <option value="">— none —</option>
                {available.map((o) => (
                  <option
                    key={o.option_id}
                    value={o.option_id}
                    disabled={idx === 0 && o.is_full}
                  >
                    {o.course_code} — {o.course_title}
                    {o.is_full ? " (full)" : ""}
                  </option>
                ))}
              </Select>
            </Field>
          );
        })}
      </div>

      <p className="mt-3 text-xs text-zinc-500">
        Tip: set fallbacks at rank 2 and 3 so the cascade can re-route you
        automatically if your 1st choice is later dissolved. If you set only
        your 1st choice and it&apos;s later dissolved, your HOD will contact
        you to pick a replacement.
      </p>

      <div className="mt-3 flex flex-wrap gap-2 text-xs text-zinc-600">
        {group.options.map((o) => (
          <span
            key={o.option_id}
            className="rounded border border-zinc-200 bg-zinc-50 px-2 py-1"
          >
            {o.course_code} · {o.current_enrollment}
            {o.max_enrollment != null ? `/${o.max_enrollment}` : ""}
            {o.is_full ? " · full" : ""}
            {o.is_dissolved ? " · dissolved" : ""}
          </span>
        ))}
      </div>
    </Card>
  );
}
