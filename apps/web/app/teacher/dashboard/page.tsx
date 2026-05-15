"use client";

import { useEffect, useMemo, useState } from "react";

import { ApiError, api } from "@/lib/api";
import {
  Badge,
  Card,
  ErrorText,
  Loading,
} from "@/components/ui";

type SessionState = "pending" | "open" | "closed";

type ClassSession = {
  id: string;
  course_offering_id: string;
  scheduled_date: string; // YYYY-MM-DD
  start_time: string; // HH:MM:SS
  end_time: string;
  state: SessionState;
};

type CourseOffering = {
  id: string;
  course_id: string;
  section_id: string;
  academic_term: string;
};

type Course = {
  id: string;
  code: string;
  title: string;
};

type Section = {
  id: string;
  name: string;
};

type ApiPage<T> = { items: T[]; total: number };

// Returns Monday's date for the week containing `d`, normalized to midnight.
function mondayOf(d: Date): Date {
  const out = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const dow = (out.getDay() + 6) % 7; // 0..6 with Monday=0
  out.setDate(out.getDate() - dow);
  return out;
}

function isoDate(d: Date): string {
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function addDays(d: Date, n: number): Date {
  const out = new Date(d);
  out.setDate(out.getDate() + n);
  return out;
}

function fmtHM(t: string): string {
  return t.slice(0, 5);
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"];

export default function TeacherDashboardPage() {
  const [sessions, setSessions] = useState<ClassSession[]>([]);
  const [offerings, setOfferings] = useState<CourseOffering[]>([]);
  const [coursesById, setCoursesById] = useState<Record<string, Course>>({});
  const [sectionsById, setSectionsById] = useState<Record<string, Section>>({});
  const [weekStart, setWeekStart] = useState<Date>(() => mondayOf(new Date()));
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const weekEnd = useMemo(() => addDays(weekStart, 4), [weekStart]);

  useEffect(() => {
    (async () => {
      setLoading(true);
      setErr(null);
      try {
        const me = await api<{ id: string }>("/users/me");
        // Load offerings + their course/section catalogues once. Sessions
        // re-fetch when the week changes.
        const [offs, courses, sections] = await Promise.all([
          api<ApiPage<CourseOffering>>("/course-offerings", {
            query: { teacher_user_id: me.id, limit: 200 },
          }),
          api<ApiPage<Course>>("/courses", { query: { limit: 500 } }),
          api<ApiPage<Section>>("/sections", { query: { limit: 200 } }),
        ]);
        setOfferings(offs.items);
        setCoursesById(Object.fromEntries(courses.items.map((c) => [c.id, c])));
        setSectionsById(
          Object.fromEntries(sections.items.map((s) => [s.id, s])),
        );
      } catch (e) {
        setErr(e instanceof ApiError ? e.message : "load failed");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const rows = await api<ClassSession[]>("/sessions", {
          query: {
            from: isoDate(weekStart),
            to: isoDate(weekEnd),
          },
        });
        setSessions(rows);
      } catch (e) {
        setErr(e instanceof ApiError ? e.message : "load failed");
      }
    })();
  }, [weekStart, weekEnd]);

  // Group sessions by weekday index (0..4 Mon..Fri).
  const byDay = useMemo(() => {
    const out: ClassSession[][] = [[], [], [], [], []];
    for (const s of sessions) {
      const d = new Date(s.scheduled_date + "T00:00:00");
      const idx = (d.getDay() + 6) % 7;
      if (idx >= 0 && idx <= 4) out[idx].push(s);
    }
    for (const day of out) day.sort((a, b) => a.start_time.localeCompare(b.start_time));
    return out;
  }, [sessions]);

  const offeringById = useMemo(
    () => Object.fromEntries(offerings.map((o) => [o.id, o])),
    [offerings],
  );

  function label(off: CourseOffering | undefined): {
    code: string;
    section: string;
  } {
    if (!off) return { code: "—", section: "" };
    const course = coursesById[off.course_id];
    const sec = sectionsById[off.section_id];
    return {
      code: course?.code ?? "—",
      section: sec?.name ?? "",
    };
  }

  function stateTone(s: SessionState): "neutral" | "green" | "amber" {
    if (s === "open") return "green";
    if (s === "closed") return "neutral";
    return "amber";
  }

  if (err) return <ErrorText>{err}</ErrorText>;
  if (loading) return <Loading />;

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-lg font-semibold text-zinc-900">Dashboard</h1>
          <p className="text-sm text-zinc-500">
            Your week — {isoDate(weekStart)} → {isoDate(weekEnd)}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            className="rounded border border-zinc-200 bg-white px-3 py-1.5 text-sm hover:bg-zinc-50"
            onClick={() => setWeekStart((d) => addDays(d, -7))}
          >
            ← Prev
          </button>
          <button
            type="button"
            className="rounded border border-zinc-200 bg-white px-3 py-1.5 text-sm hover:bg-zinc-50"
            onClick={() => setWeekStart(mondayOf(new Date()))}
          >
            This week
          </button>
          <button
            type="button"
            className="rounded border border-zinc-200 bg-white px-3 py-1.5 text-sm hover:bg-zinc-50"
            onClick={() => setWeekStart((d) => addDays(d, 7))}
          >
            Next →
          </button>
        </div>
      </div>

      <Card className="overflow-x-auto">
        <div className="border-b border-zinc-200 px-4 py-3 text-sm font-semibold text-zinc-900">
          Weekly timetable
        </div>
        <div className="grid grid-cols-5 gap-2 p-4">
          {WEEKDAYS.map((wd, i) => {
            const dayDate = addDays(weekStart, i);
            const cells = byDay[i];
            return (
              <div
                key={wd}
                className="min-h-[140px] rounded border border-zinc-200 bg-zinc-50/40 p-2"
              >
                <div className="mb-2 flex items-baseline justify-between">
                  <div className="text-xs font-semibold text-zinc-700">{wd}</div>
                  <div className="text-[10px] text-zinc-500">
                    {isoDate(dayDate).slice(5)}
                  </div>
                </div>
                {cells.length === 0 ? (
                  <p className="text-[11px] text-zinc-400">No classes</p>
                ) : (
                  <ul className="space-y-1.5">
                    {cells.map((s) => {
                      const l = label(offeringById[s.course_offering_id]);
                      return (
                        <li
                          key={s.id}
                          className="rounded border border-zinc-200 bg-white p-1.5 text-[11px]"
                        >
                          <div className="flex items-center justify-between gap-1">
                            <span className="font-medium">{l.code}</span>
                            <Badge tone={stateTone(s.state)}>{s.state}</Badge>
                          </div>
                          <div className="text-zinc-500">
                            {fmtHM(s.start_time)}–{fmtHM(s.end_time)}
                            {l.section ? ` · ${l.section}` : ""}
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            );
          })}
        </div>
      </Card>

      <Card className="overflow-x-auto">
        <div className="border-b border-zinc-200 px-4 py-3 text-sm font-semibold text-zinc-900">
          My offerings ({offerings.length})
        </div>
        {offerings.length === 0 ? (
          <p className="px-4 py-6 text-sm text-zinc-500">
            You have no offerings this term.
          </p>
        ) : (
          <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-3">
            {offerings.map((o) => {
              const l = label(o);
              const course = coursesById[o.course_id];
              return (
                <div
                  key={o.id}
                  className="rounded border border-zinc-200 bg-white p-3"
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate font-medium">{l.code}</div>
                      <div className="truncate text-xs text-zinc-500">
                        {course?.title ?? ""}
                      </div>
                    </div>
                    <Badge tone="neutral">{l.section}</Badge>
                  </div>
                  <div className="mt-2 text-[11px] text-zinc-500">
                    {o.academic_term}
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2 text-xs">
                    <a
                      href={`/teacher/courses/${o.id}`}
                      className="text-zinc-900 underline"
                    >
                      Open →
                    </a>
                    <a
                      href={`/teacher/courses/${o.id}/scheme`}
                      className="text-zinc-700 underline"
                    >
                      Scheme
                    </a>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>
    </div>
  );
}
