"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  ErrorText,
  Field,
  Input,
  Loading,
} from "@/components/ui";

type SessionState = "pending" | "open" | "closed";
type ClassSession = {
  id: string;
  course_offering_id: string;
  scheduled_date: string;
  start_time: string;
  end_time: string;
  state: SessionState;
};

type AttendanceRecord = {
  id: string;
  class_session_id: string;
  state: "submitted" | "verified" | "recorded" | "flagged";
  flagged_reason: string | null;
  gps_distance_m: number | null;
};

// Audit Session 5 — eligibility summary
type CourseType = "theory" | "lab" | "integrated" | "nptel";

type CourseEligibility = {
  course_offering_id: string;
  course_code: string;
  course_title: string;
  course_type: CourseType;
  attendance_percent: number;
  cie_percent: number | null;
  attendance_eligible: boolean;
  cie_eligible: boolean;
  overall_eligible: boolean;
  reason: string | null;
};

type EligibilitySummary = {
  academic_term_id: string | null;
  academic_term_code: string | null;
  courses: CourseEligibility[];
};

const DEVICE_KEY = "metis.device_fp";

function deviceFingerprint(): string {
  if (typeof window === "undefined") return "ssr";
  let v = window.localStorage.getItem(DEVICE_KEY);
  if (v) return v;
  const rnd =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : Math.random().toString(36).slice(2);
  v = `${rnd}|${navigator.userAgent.slice(0, 80)}`;
  window.localStorage.setItem(DEVICE_KEY, v);
  return v;
}

async function readGps(): Promise<{ lat: number; lon: number }> {
  return new Promise((resolve, reject) => {
    if (!("geolocation" in navigator)) {
      reject(new Error("Geolocation not supported by this browser"));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) =>
        resolve({ lat: pos.coords.latitude, lon: pos.coords.longitude }),
      (err) => reject(new Error(err.message || "GPS permission denied")),
      { enableHighAccuracy: true, timeout: 15_000 },
    );
  });
}

function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function StudentAttendancePage() {
  const [sessions, setSessions] = useState<ClassSession[] | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<AttendanceRecord | null>(null);
  const [submitErr, setSubmitErr] = useState<string | null>(null);
  const [summary, setSummary] = useState<EligibilitySummary | null>(null);

  const reload = useCallback(async () => {
    setLoadErr(null);
    try {
      const rows = await api<ClassSession[]>("/sessions", {
        query: { from: today(), to: today() },
      });
      setSessions(rows);
    } catch (e) {
      setLoadErr(e instanceof ApiError ? e.message : "failed to load");
    }
    // Audit Session 5 — eligibility cards. Non-fatal if it 404s for a
    // student who has no active enrollment yet.
    try {
      const s = await api<EligibilitySummary>(
        "/attendance/me/eligibility-summary",
      );
      setSummary(s);
    } catch {
      setSummary(null);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const submit = async () => {
    setBusy(true);
    setSubmitErr(null);
    setResult(null);
    try {
      const trimmed = token.trim();
      if (!trimmed) throw new Error("Paste the QR token first");
      const gps = await readGps();
      const rec = await api<AttendanceRecord>("/attendance/submit", {
        method: "POST",
        body: {
          qr_token: trimmed,
          gps_lat: gps.lat.toFixed(6),
          gps_lon: gps.lon.toFixed(6),
          device_fingerprint: deviceFingerprint(),
        },
      });
      setResult(rec);
      setToken("");
    } catch (e) {
      setSubmitErr(
        e instanceof ApiError ? e.message : (e as Error).message,
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-lg font-semibold">Mark attendance</h1>
        <p className="text-xs text-zinc-500">
          Scan the QR your teacher displayed, then submit. Your location is
          checked against the classroom; the camera frame is discarded after
          face verification.
        </p>
      </header>

      {summary && summary.courses.length > 0 ? (
        <Card className="p-4">
          <div className="mb-3 flex items-baseline justify-between">
            <h2 className="text-sm font-semibold">
              Eligibility this term
              {summary.academic_term_code ? (
                <span className="ml-2 text-xs font-normal text-zinc-500">
                  {summary.academic_term_code}
                </span>
              ) : null}
            </h2>
            <span className="text-[11px] text-zinc-400">
              Attendance ≥85% · CIE ≥40%
            </span>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {summary.courses.map((c) => (
              <EligibilityCard key={c.course_offering_id} c={c} />
            ))}
          </div>
        </Card>
      ) : null}

      <Card className="p-4">
        <h2 className="mb-3 text-sm font-semibold">Submit</h2>
        <Field label="QR token (scan or paste)" htmlFor="qr">
          <Input
            id="qr"
            placeholder="eyJhbGciOi…"
            value={token}
            onChange={(e) => setToken(e.target.value)}
          />
        </Field>
        <p className="mt-2 text-[11px] text-zinc-400">
          A QR scanner ships in a follow-up. For now, paste the token your
          teacher&apos;s screen shows under &quot;token (debug)&quot;.
        </p>
        <div className="mt-3 flex items-center gap-2">
          <Button onClick={submit} disabled={busy}>
            {busy ? "Submitting…" : "Submit"}
          </Button>
          {result ? (
            <Badge tone={result.state === "recorded" ? "green" : "amber"}>
              {result.state}
              {result.flagged_reason ? ` (${result.flagged_reason})` : ""}
            </Badge>
          ) : null}
        </div>
        <ErrorText>{submitErr}</ErrorText>
      </Card>

      <Card className="p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold">Today&apos;s classes</h2>
          <Button variant="secondary" size="sm" onClick={reload}>
            Reload
          </Button>
        </div>
        <ErrorText>{loadErr}</ErrorText>
        {sessions === null ? (
          <Loading />
        ) : sessions.length === 0 ? (
          <p className="text-sm text-zinc-500">
            No classes scheduled today.
          </p>
        ) : (
          <ul className="space-y-1 text-sm">
            {sessions.map((s) => (
              <li
                key={s.id}
                className="flex items-center justify-between border-b border-zinc-100 py-1 last:border-0"
              >
                <span>
                  {s.start_time.slice(0, 5)}–{s.end_time.slice(0, 5)}
                </span>
                <Badge
                  tone={
                    s.state === "open"
                      ? "green"
                      : s.state === "closed"
                        ? "neutral"
                        : "amber"
                  }
                >
                  {s.state}
                </Badge>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

// ── Audit Session 5 — per-course eligibility card ─────────────────────────
function EligibilityCard({ c }: { c: CourseEligibility }) {
  const pct = c.attendance_percent;
  const pctText = pct.toFixed(1) + "%";
  const isNptel = c.course_type === "nptel";
  return (
    <div className="rounded border border-zinc-200 bg-white p-3">
      <div className="flex items-baseline justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate font-medium">{c.course_code}</div>
          <div className="truncate text-xs text-zinc-500">{c.course_title}</div>
        </div>
        <Badge tone={c.overall_eligible ? "green" : "red"}>
          {c.overall_eligible ? "eligible" : "ineligible"}
        </Badge>
      </div>
      <div className="mt-3 flex items-baseline gap-3">
        {isNptel ? (
          <span className="text-sm text-zinc-600">NPTEL — eligibility waived</span>
        ) : (
          <>
            <div className="text-2xl font-semibold tabular-nums">{pctText}</div>
            <div className="text-[11px] text-zinc-500">attendance</div>
          </>
        )}
      </div>
      {!isNptel ? (
        <div className="mt-2 flex flex-wrap gap-2 text-[11px]">
          <Badge tone={c.attendance_eligible ? "green" : "red"}>
            Attendance ≥85%{c.attendance_eligible ? " ✓" : " ✗"}
          </Badge>
          <Badge tone={c.cie_eligible ? "green" : "red"}>
            CIE ≥40%
            {c.cie_percent != null ? ` (${c.cie_percent.toFixed(1)}%)` : " (pending)"}
            {c.cie_eligible ? " ✓" : " ✗"}
          </Badge>
        </div>
      ) : null}
      {c.reason ? (
        <p className="mt-2 text-[11px] text-red-700">{c.reason}</p>
      ) : null}
    </div>
  );
}
