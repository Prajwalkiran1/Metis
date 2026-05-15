"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { ApiError, api } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  ErrorText,
  Field,
  Input,
  Loading,
  Select,
  Table,
  Tabs,
  Td,
  Th,
} from "@/components/ui";

type Offering = {
  id: string;
  course_id: string;
  section_id: string;
  teacher_user_id: string;
  academic_term: string;
  semester: number;
  is_active: boolean;
};

type Course = {
  id: string;
  code: string;
  title: string;
  course_type: "theory" | "lab" | "integrated" | "nptel";
};

type Room = { id: string; code: string; room_type: string };

type Exception = {
  id: string;
  course_offering_id: string;
  original_slot_id: string | null;
  exception_date: string;
  kind: "extra" | "reschedule" | "room_change" | "cancel";
  new_room_id: string | null;
  new_start_time: string | null;
  new_end_time: string | null;
  reason: string | null;
  created_at: string;
};

type TabId = "extra" | "reschedule" | "room-change";

const extraSchema = z.object({
  exception_date: z.string().min(1),
  new_start_time: z.string().min(1),
  new_end_time: z.string().min(1),
  new_room_id: z.string().uuid(),
  reason: z.string().max(200).optional(),
});

const rescheduleSchema = z.object({
  exception_date: z.string().min(1),
  new_start_time: z.string().min(1),
  new_end_time: z.string().min(1),
  new_room_id: z.string().uuid().optional().or(z.literal("")),
  reason: z.string().max(200).optional(),
});

const roomChangeSchema = z.object({
  exception_date: z.string().min(1),
  new_room_id: z.string().uuid(),
  reason: z.string().max(200).optional(),
});

type ExtraValues = z.infer<typeof extraSchema>;
type RescheduleValues = z.infer<typeof rescheduleSchema>;
type RoomChangeValues = z.infer<typeof roomChangeSchema>;

function fmtTime(t: string | null) {
  if (!t) return "—";
  return t.slice(0, 5);
}

export default function TeacherCoursePage() {
  const params = useParams<{ id: string }>();
  const offeringId = params.id;

  const [offering, setOffering] = useState<Offering | null>(null);
  const [course, setCourse] = useState<Course | null>(null);
  const [rooms, setRooms] = useState<Room[]>([]);
  const [exceptions, setExceptions] = useState<Exception[] | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [tab, setTab] = useState<TabId>("extra");
  const [submitErr, setSubmitErr] = useState<string | null>(null);

  const refreshExceptions = useCallback(async () => {
    try {
      const rows = await api<Exception[]>(
        `/offerings/${offeringId}/timetable-exceptions`,
      );
      setExceptions(rows);
    } catch (e) {
      setLoadErr(e instanceof ApiError ? e.message : "load failed");
    }
  }, [offeringId]);

  useEffect(() => {
    (async () => {
      try {
        const off = await api<Offering>(`/course-offerings/${offeringId}`);
        setOffering(off);
        const [c, roomPage] = await Promise.all([
          api<Course>(`/courses/${off.course_id}`),
          api<{ items: Room[]; total: number }>("/rooms", {
            query: { page_size: 200 },
          }),
        ]);
        setCourse(c);
        setRooms(roomPage.items);
      } catch (e) {
        setLoadErr(e instanceof ApiError ? e.message : "load failed");
      }
      await refreshExceptions();
    })();
  }, [offeringId, refreshExceptions]);

  const roomLabel = useCallback(
    (id: string | null) => {
      if (!id) return "—";
      const r = rooms.find((x) => x.id === id);
      return r ? r.code : id.slice(0, 8);
    },
    [rooms],
  );

  const handleDelete = useCallback(
    async (exceptionId: string) => {
      if (!confirm("Delete this exception?")) return;
      try {
        await api(
          `/offerings/${offeringId}/timetable-exceptions/${exceptionId}`,
          { method: "DELETE" },
        );
        await refreshExceptions();
      } catch (e) {
        setSubmitErr(e instanceof ApiError ? e.message : "delete failed");
      }
    },
    [offeringId, refreshExceptions],
  );

  if (loadErr) return <ErrorText>{loadErr}</ErrorText>;
  if (offering === null || course === null || exceptions === null)
    return <Loading />;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-zinc-900">
          {course.code} · {course.title}
        </h1>
        <p className="text-sm text-zinc-500">
          {offering.academic_term} · semester {offering.semester} ·{" "}
          <Badge tone="neutral">{course.course_type}</Badge>
        </p>
        <div className="mt-2 flex gap-3 text-sm">
          <Link
            href={`/teacher/courses/${offeringId}/scheme`}
            className="text-zinc-900 underline"
          >
            Assessment scheme →
          </Link>
          <Link href="/teacher/attendance" className="text-zinc-900 underline">
            Take attendance →
          </Link>
        </div>
      </div>

      <Card className="p-4">
        <h2 className="text-sm font-semibold text-zinc-900">
          Record an ad-hoc class session
        </h2>
        <p className="mt-1 text-xs text-zinc-500">
          Use these forms to schedule an extra class, reschedule a single
          occurrence to a different time, or swap the room for one date. The
          attendance materialiser picks up the new row automatically.
        </p>
        <div className="mt-3">
          <Tabs
            tabs={[
              { id: "extra", label: "Extra class" },
              { id: "reschedule", label: "Reschedule" },
              { id: "room-change", label: "Room change" },
            ]}
            active={tab}
            onChange={(id) => {
              setTab(id as TabId);
              setSubmitErr(null);
            }}
          />
        </div>
        <div className="mt-4">
          {tab === "extra" && (
            <ExtraForm
              offeringId={offeringId}
              rooms={rooms}
              onSuccess={refreshExceptions}
              onError={setSubmitErr}
            />
          )}
          {tab === "reschedule" && (
            <RescheduleForm
              offeringId={offeringId}
              rooms={rooms}
              onSuccess={refreshExceptions}
              onError={setSubmitErr}
            />
          )}
          {tab === "room-change" && (
            <RoomChangeForm
              offeringId={offeringId}
              rooms={rooms}
              onSuccess={refreshExceptions}
              onError={setSubmitErr}
            />
          )}
          {submitErr ? <ErrorText>{submitErr}</ErrorText> : null}
        </div>
      </Card>

      <Card className="p-4">
        <h2 className="text-sm font-semibold text-zinc-900">
          Recent exceptions
        </h2>
        {exceptions.length === 0 ? (
          <p className="mt-2 text-sm text-zinc-500">
            No exceptions yet. Anything you record above will show up here.
          </p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <Table>
              <thead>
                <tr>
                  <Th>Date</Th>
                  <Th>Kind</Th>
                  <Th>Time</Th>
                  <Th>Room</Th>
                  <Th>Reason</Th>
                  <Th></Th>
                </tr>
              </thead>
              <tbody>
                {exceptions.map((e) => (
                  <tr key={e.id}>
                    <Td>{e.exception_date}</Td>
                    <Td>
                      <Badge tone="neutral">{e.kind}</Badge>
                    </Td>
                    <Td>
                      {e.new_start_time
                        ? `${fmtTime(e.new_start_time)}–${fmtTime(e.new_end_time)}`
                        : "—"}
                    </Td>
                    <Td>{roomLabel(e.new_room_id)}</Td>
                    <Td className="max-w-xs truncate text-xs text-zinc-500">
                      {e.reason || "—"}
                    </Td>
                    <Td>
                      <button
                        type="button"
                        className="text-xs text-red-600 underline"
                        onClick={() => handleDelete(e.id)}
                      >
                        Delete
                      </button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
        )}
      </Card>
    </div>
  );
}

function ExtraForm({
  offeringId,
  rooms,
  onSuccess,
  onError,
}: {
  offeringId: string;
  rooms: Room[];
  onSuccess: () => Promise<void>;
  onError: (msg: string | null) => void;
}) {
  const form = useForm<ExtraValues>({ resolver: zodResolver(extraSchema) });
  const onSubmit = form.handleSubmit(async (values) => {
    onError(null);
    try {
      await api(`/offerings/${offeringId}/timetable-exceptions/extra`, {
        method: "POST",
        body: { ...values, reason: values.reason || null },
      });
      form.reset();
      await onSuccess();
    } catch (e) {
      onError(e instanceof ApiError ? e.message : "create failed");
    }
  });
  return (
    <form onSubmit={onSubmit} className="grid gap-3 md:grid-cols-2">
      <Field label="Date">
        <Input type="date" {...form.register("exception_date")} />
      </Field>
      <Field label="Room">
        <Select {...form.register("new_room_id")} defaultValue="">
          <option value="" disabled>
            Pick a room
          </option>
          {rooms.map((r) => (
            <option key={r.id} value={r.id}>
              {r.code} ({r.room_type})
            </option>
          ))}
        </Select>
      </Field>
      <Field label="Start time">
        <Input type="time" step="60" {...form.register("new_start_time")} />
      </Field>
      <Field label="End time">
        <Input type="time" step="60" {...form.register("new_end_time")} />
      </Field>
      <Field label="Reason (optional)">
        <Input maxLength={200} {...form.register("reason")} />
      </Field>
      <div className="flex items-end">
        <Button type="submit" disabled={form.formState.isSubmitting}>
          Record extra class
        </Button>
      </div>
    </form>
  );
}

function RescheduleForm({
  offeringId,
  rooms,
  onSuccess,
  onError,
}: {
  offeringId: string;
  rooms: Room[];
  onSuccess: () => Promise<void>;
  onError: (msg: string | null) => void;
}) {
  const form = useForm<RescheduleValues>({
    resolver: zodResolver(rescheduleSchema),
  });
  const onSubmit = form.handleSubmit(async (values) => {
    onError(null);
    try {
      await api(`/offerings/${offeringId}/timetable-exceptions/reschedule`, {
        method: "POST",
        body: {
          exception_date: values.exception_date,
          new_start_time: values.new_start_time,
          new_end_time: values.new_end_time,
          new_room_id: values.new_room_id || null,
          reason: values.reason || null,
        },
      });
      form.reset();
      await onSuccess();
    } catch (e) {
      onError(e instanceof ApiError ? e.message : "create failed");
    }
  });
  return (
    <form onSubmit={onSubmit} className="grid gap-3 md:grid-cols-2">
      <Field label="Date (must fall on the slot's weekday)">
        <Input type="date" {...form.register("exception_date")} />
      </Field>
      <Field label="New room (optional, blank = keep slot's room)">
        <Select {...form.register("new_room_id")} defaultValue="">
          <option value="">Keep original room</option>
          {rooms.map((r) => (
            <option key={r.id} value={r.id}>
              {r.code} ({r.room_type})
            </option>
          ))}
        </Select>
      </Field>
      <Field label="New start time">
        <Input type="time" step="60" {...form.register("new_start_time")} />
      </Field>
      <Field label="New end time">
        <Input type="time" step="60" {...form.register("new_end_time")} />
      </Field>
      <Field label="Reason (optional)">
        <Input maxLength={200} {...form.register("reason")} />
      </Field>
      <div className="flex items-end">
        <Button type="submit" disabled={form.formState.isSubmitting}>
          Reschedule
        </Button>
      </div>
    </form>
  );
}

function RoomChangeForm({
  offeringId,
  rooms,
  onSuccess,
  onError,
}: {
  offeringId: string;
  rooms: Room[];
  onSuccess: () => Promise<void>;
  onError: (msg: string | null) => void;
}) {
  const form = useForm<RoomChangeValues>({
    resolver: zodResolver(roomChangeSchema),
  });
  const onSubmit = form.handleSubmit(async (values) => {
    onError(null);
    try {
      await api(`/offerings/${offeringId}/timetable-exceptions/room-change`, {
        method: "POST",
        body: { ...values, reason: values.reason || null },
      });
      form.reset();
      await onSuccess();
    } catch (e) {
      onError(e instanceof ApiError ? e.message : "create failed");
    }
  });
  return (
    <form onSubmit={onSubmit} className="grid gap-3 md:grid-cols-2">
      <Field label="Date (must fall on the slot's weekday)">
        <Input type="date" {...form.register("exception_date")} />
      </Field>
      <Field label="New room">
        <Select {...form.register("new_room_id")} defaultValue="">
          <option value="" disabled>
            Pick a room
          </option>
          {rooms.map((r) => (
            <option key={r.id} value={r.id}>
              {r.code} ({r.room_type})
            </option>
          ))}
        </Select>
      </Field>
      <Field label="Reason (optional)">
        <Input maxLength={200} {...form.register("reason")} />
      </Field>
      <div className="flex items-end">
        <Button type="submit" disabled={form.formState.isSubmitting}>
          Change room
        </Button>
      </div>
    </form>
  );
}
