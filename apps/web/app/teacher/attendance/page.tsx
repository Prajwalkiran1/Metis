"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { QRCodeSVG } from "qrcode.react";

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

type SessionState = "pending" | "open" | "closed";
type RecordState = "submitted" | "verified" | "recorded" | "flagged";

type ClassSession = {
  id: string;
  course_offering_id: string;
  scheduled_date: string;
  start_time: string;
  end_time: string;
  state: SessionState;
};

type QRTokenOut = {
  token: string;
  jti: string;
  session_id: string;
  valid_from: string;
  valid_until: string;
  ttl_seconds: number;
};

type AttendanceRecord = {
  id: string;
  state: RecordState;
  submitted_at: string;
  flagged_reason: string | null;
  gps_distance_m: number | null;
};

type SessionFeedRow = {
  student_user_id: string;
  student_name: string;
  student_email: string;
  record: AttendanceRecord | null;
};

type SessionFeed = {
  session: ClassSession;
  rows: SessionFeedRow[];
  counts: Record<string, number>;
};

function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function TeacherAttendancePage() {
  const [sessions, setSessions] = useState<ClassSession[] | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [active, setActive] = useState<ClassSession | null>(null);

  const reloadSessions = useCallback(async () => {
    setLoadErr(null);
    try {
      const rows = await api<ClassSession[]>("/sessions", {
        query: { from: today(), to: today() },
      });
      setSessions(rows);
    } catch (e) {
      setLoadErr(e instanceof ApiError ? e.message : "failed to load sessions");
    }
  }, []);

  useEffect(() => {
    reloadSessions();
  }, [reloadSessions]);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-lg font-semibold">Attendance</h1>
        <p className="text-xs text-zinc-500">
          Today&apos;s sessions. Start the QR to open the class for submits.
        </p>
      </header>

      <Card className="p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold">Today&apos;s sessions</h2>
          <Button variant="secondary" size="sm" onClick={reloadSessions}>
            Reload
          </Button>
        </div>
        <ErrorText>{loadErr}</ErrorText>
        {sessions === null ? (
          <Loading />
        ) : sessions.length === 0 ? (
          <p className="text-sm text-zinc-500">
            No sessions today. If the timetable says otherwise, run{" "}
            <code className="rounded bg-zinc-100 px-1 py-0.5 text-xs">
              npm run materialise
            </code>
            .
          </p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Time</Th>
                <Th>Session</Th>
                <Th>State</Th>
                <Th></Th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => (
                <tr key={s.id}>
                  <Td>
                    {s.start_time.slice(0, 5)}–{s.end_time.slice(0, 5)}
                  </Td>
                  <Td className="font-mono text-xs">{s.id.slice(0, 8)}…</Td>
                  <Td>
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
                  </Td>
                  <Td>
                    <Button size="sm" onClick={() => setActive(s)}>
                      Open
                    </Button>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      {active !== null ? (
        <ActiveSession
          session={active}
          onClosed={async () => {
            await reloadSessions();
            setActive(null);
          }}
        />
      ) : null}
    </div>
  );
}

function ActiveSession({
  session,
  onClosed,
}: {
  session: ClassSession;
  onClosed: () => void;
}) {
  const [qr, setQr] = useState<QRTokenOut | null>(null);
  const [qrErr, setQrErr] = useState<string | null>(null);
  const [feed, setFeed] = useState<SessionFeed | null>(null);
  const [feedErr, setFeedErr] = useState<string | null>(null);

  const issueQr = useCallback(async () => {
    setQrErr(null);
    try {
      const t = await api<QRTokenOut>(`/sessions/${session.id}/qr`, {
        method: "POST",
      });
      setQr(t);
    } catch (e) {
      setQrErr(e instanceof ApiError ? e.message : "failed to start QR");
    }
  }, [session.id]);

  const reloadFeed = useCallback(async () => {
    setFeedErr(null);
    try {
      const f = await api<SessionFeed>(`/attendance/session/${session.id}`);
      setFeed(f);
    } catch (e) {
      setFeedErr(e instanceof ApiError ? e.message : "failed to load feed");
    }
  }, [session.id]);

  useEffect(() => {
    reloadFeed();
  }, [reloadFeed]);

  // Rotate QR ~10s before exp so we never serve an expired token. Poll feed
  // every 5s while a QR is live.
  useEffect(() => {
    if (qr === null) return;
    const expMs = new Date(qr.valid_until).getTime();
    const refreshIn = Math.max(1000, expMs - Date.now() - 10_000);
    const rotateTimer = setTimeout(issueQr, refreshIn);
    return () => clearTimeout(rotateTimer);
  }, [qr, issueQr]);

  useEffect(() => {
    const id = setInterval(reloadFeed, 5_000);
    return () => clearInterval(id);
  }, [reloadFeed]);

  const closeSession = async () => {
    try {
      await api(`/sessions/${session.id}/close`, { method: "POST" });
      setQr(null);
      onClosed();
    } catch (e) {
      setFeedErr(e instanceof ApiError ? e.message : "failed to close session");
    }
  };

  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold">
            Session {session.id.slice(0, 8)}…
          </h2>
          <p className="text-xs text-zinc-500">
            {session.scheduled_date} · {session.start_time.slice(0, 5)}–
            {session.end_time.slice(0, 5)}
          </p>
        </div>
        <div className="flex gap-2">
          {qr === null ? (
            <Button onClick={issueQr}>Start QR</Button>
          ) : (
            <Button variant="secondary" onClick={issueQr}>
              Rotate now
            </Button>
          )}
          <Button variant="danger" onClick={closeSession}>
            Close session
          </Button>
        </div>
      </div>
      <ErrorText>{qrErr}</ErrorText>

      <div className="grid gap-6 md:grid-cols-2">
        <div className="flex items-center justify-center">
          {qr ? (
            <QRCodeBlock qr={qr} />
          ) : (
            <p className="text-sm text-zinc-500">QR not started.</p>
          )}
        </div>

        <div>
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-semibold">Live feed</h3>
            <Button variant="secondary" size="sm" onClick={reloadFeed}>
              Refresh
            </Button>
          </div>
          <ErrorText>{feedErr}</ErrorText>
          {feed === null ? (
            <Loading />
          ) : (
            <FeedRows session={session} feed={feed} onChange={reloadFeed} />
          )}
        </div>
      </div>
    </Card>
  );
}

function QRCodeBlock({ qr }: { qr: QRTokenOut }) {
  const [secondsLeft, setSecondsLeft] = useState(qr.ttl_seconds);
  useEffect(() => {
    const id = setInterval(() => {
      const left = Math.max(
        0,
        Math.round((new Date(qr.valid_until).getTime() - Date.now()) / 1000),
      );
      setSecondsLeft(left);
    }, 500);
    return () => clearInterval(id);
  }, [qr]);
  return (
    <div className="flex flex-col items-center gap-3">
      <div className="rounded bg-white p-3 shadow-sm">
        <QRCodeSVG value={qr.token} size={220} level="M" />
      </div>
      <p className="text-xs text-zinc-500">expires in {secondsLeft}s</p>
      <details className="w-full text-xs">
        <summary className="cursor-pointer text-zinc-400">
          token (debug)
        </summary>
        <code className="mt-1 block break-all rounded bg-zinc-100 p-2 font-mono text-[10px]">
          {qr.token}
        </code>
      </details>
    </div>
  );
}

function FeedRows({
  session,
  feed,
  onChange,
}: {
  session: ClassSession;
  feed: SessionFeed;
  onChange: () => void;
}) {
  const totalKey = useMemo(
    () =>
      ["recorded", "flagged", "verified", "submitted", "absent"]
        .map((k) => `${k}=${feed.counts[k] ?? 0}`)
        .join(" · "),
    [feed],
  );
  return (
    <div>
      <p className="mb-2 text-xs text-zinc-500">{totalKey}</p>
      <div className="max-h-[420px] overflow-auto">
        <Table>
          <thead>
            <tr>
              <Th>Student</Th>
              <Th>State</Th>
              <Th></Th>
            </tr>
          </thead>
          <tbody>
            {feed.rows.map((row) => (
              <tr key={row.student_user_id}>
                <Td>
                  <div className="text-sm">{row.student_name}</div>
                  <div className="text-[10px] text-zinc-500">
                    {row.student_email}
                  </div>
                </Td>
                <Td>
                  {row.record === null ? (
                    <Badge tone="neutral">absent</Badge>
                  ) : row.record.state === "recorded" ? (
                    <Badge tone="green">recorded</Badge>
                  ) : row.record.state === "flagged" ? (
                    <span title={row.record.flagged_reason ?? ""}>
                      <Badge tone="amber">flagged</Badge>
                    </span>
                  ) : (
                    <Badge>{row.record.state}</Badge>
                  )}
                </Td>
                <Td>
                  {row.record === null ? (
                    <OverrideButton
                      session={session}
                      label="Mark present"
                      payload={{
                        to_state: "recorded",
                        reason: "manual: student present",
                        student_user_id: row.student_user_id,
                      }}
                      onDone={onChange}
                    />
                  ) : row.record.state === "flagged" ? (
                    <OverrideButton
                      session={session}
                      label="Approve"
                      recordId={row.record.id}
                      payload={{
                        to_state: "recorded",
                        reason: "teacher review: ok",
                      }}
                      onDone={onChange}
                    />
                  ) : null}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </div>
    </div>
  );
}

function OverrideButton({
  session,
  recordId,
  label,
  payload,
  onDone,
}: {
  session: ClassSession;
  recordId?: string;
  label: string;
  payload: {
    to_state: RecordState;
    reason: string;
    student_user_id?: string;
  };
  onDone: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  return (
    <div>
      <Button
        size="sm"
        variant="secondary"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setErr(null);
          try {
            await api(
              `/attendance/sessions/${session.id}/override`,
              {
                method: "PATCH",
                body: payload,
                query: recordId ? { record_id: recordId } : undefined,
              },
            );
            onDone();
          } catch (e) {
            setErr(e instanceof ApiError ? e.message : "override failed");
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "…" : label}
      </Button>
      <ErrorText>{err}</ErrorText>
    </div>
  );
}
