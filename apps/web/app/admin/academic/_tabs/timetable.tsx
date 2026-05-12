"use client";

import { useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { ApiError, api, type Page } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  Dialog,
  ErrorText,
  Field,
  Input,
  Loading,
  Select,
  Table,
  Td,
  Th,
} from "@/components/ui";

type Section = { id: string; batch_id: string; name: string };
type Batch = { id: string; department_id: string; name: string };
type Department = { id: string; code: string };
type CourseOffering = {
  id: string;
  course_id: string;
  section_id: string;
  teacher_user_id: string;
  academic_term: string;
  semester: number;
};
type Course = { id: string; code: string; title: string };
type Room = { id: string; code: string };
type Slot = {
  id: string;
  course_offering_id: string;
  room_id: string | null;
  day_of_week: number;
  start_time: string;
  end_time: string;
  effective_from: string;
  effective_until: string;
};
type Exception_ = {
  id: string;
  original_slot_id: string | null;
  exception_date: string;
  kind: "cancel" | "reschedule" | "room_change" | "extra";
  new_room_id: string | null;
  new_start_time: string | null;
  new_end_time: string | null;
  reason: string | null;
};
type ConflictItem = {
  type: "room" | "teacher" | "section";
  slot_id: string;
  course_offering_id: string;
  reason: string;
};
type ConflictResponse = { has_conflicts: boolean; conflicts: ConflictItem[] };
type TimetableView = {
  section_id: string;
  slots: Slot[];
  exceptions: Exception_[];
};

const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const schema = z.object({
  course_offering_id: z.string().min(1),
  room_id: z.string().optional(),
  day_of_week: z.coerce.number().int().min(0).max(6),
  start_time: z.string().min(1),
  end_time: z.string().min(1),
  effective_from: z.string().min(1),
  effective_until: z.string().min(1),
});
type FormData = z.infer<typeof schema>;

export default function TimetableTab() {
  const [depts, setDepts] = useState<Department[] | null>(null);
  const [batches, setBatches] = useState<Batch[] | null>(null);
  const [sections, setSections] = useState<Section[] | null>(null);
  const [selectedSection, setSelectedSection] = useState<string>("");
  const [view, setView] = useState<TimetableView | null>(null);
  const [offerings, setOfferings] = useState<CourseOffering[] | null>(null);
  const [courses, setCourses] = useState<Course[] | null>(null);
  const [rooms, setRooms] = useState<Room[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  async function loadInitial() {
    setErr(null);
    try {
      const [d, b, s, r, c] = await Promise.all([
        api<Page<Department>>("/departments", { query: { limit: 200 } }),
        api<Page<Batch>>("/batches", { query: { limit: 200 } }),
        api<Page<Section>>("/sections", { query: { limit: 200 } }),
        api<Page<Room>>("/rooms", { query: { limit: 200 } }),
        api<Page<Course>>("/courses", { query: { limit: 400 } }),
      ]);
      setDepts(d.items);
      setBatches(b.items);
      setSections(s.items);
      setRooms(r.items);
      setCourses(c.items);
      if (s.items[0]) setSelectedSection(s.items[0].id);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "load failed");
    }
  }

  async function loadSection() {
    if (!selectedSection) return;
    setErr(null);
    try {
      const [v, o] = await Promise.all([
        api<TimetableView>(`/timetable/${selectedSection}`),
        api<Page<CourseOffering>>("/course-offerings", {
          query: { section_id: selectedSection, limit: 100 },
        }),
      ]);
      setView(v);
      setOfferings(o.items);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "load failed");
    }
  }

  useEffect(() => {
    loadInitial();
  }, []);
  useEffect(() => {
    if (selectedSection) loadSection();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSection]);

  const sectionLabel = useMemo(() => {
    if (!sections || !batches || !depts) return (id: string) => id;
    return (id: string) => {
      const sec = sections.find((s) => s.id === id);
      if (!sec) return id;
      const batch = batches.find((b) => b.id === sec.batch_id);
      const dept = batch ? depts.find((d) => d.id === batch.department_id) : null;
      return `${dept?.code ?? "?"}-${sec.name} (${batch?.name ?? "?"})`;
    };
  }, [sections, batches, depts]);

  const courseByOffering = useMemo(() => {
    const m: Record<string, Course | undefined> = {};
    (offerings ?? []).forEach((o) => {
      m[o.id] = (courses ?? []).find((c) => c.id === o.course_id);
    });
    return m;
  }, [offerings, courses]);

  const roomById = useMemo(() => {
    const m: Record<string, Room> = {};
    (rooms ?? []).forEach((r) => (m[r.id] = r));
    return m;
  }, [rooms]);

  async function onDelete(id: string) {
    if (!confirm("Soft-delete this slot?")) return;
    try {
      await api(`/timetable/${id}`, { method: "DELETE" });
      await loadSection();
    } catch (e) {
      alert(e instanceof ApiError ? e.message : "delete failed");
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-72">
          <Field label="Section">
            <Select
              value={selectedSection}
              onChange={(e) => setSelectedSection(e.target.value)}
            >
              {(sections ?? []).map((s) => (
                <option key={s.id} value={s.id}>
                  {sectionLabel(s.id)}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <div className="ml-auto">
          <Button
            onClick={() => setOpen(true)}
            disabled={!offerings || offerings.length === 0}
          >
            Add slot
          </Button>
        </div>
      </div>

      {err && <ErrorText>{err}</ErrorText>}
      {!view && !err && <Loading />}

      {view && (
        <Card>
          <Table>
            <thead>
              <tr>
                <Th>Day</Th>
                <Th>Time</Th>
                <Th>Course</Th>
                <Th>Room</Th>
                <Th>Effective</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {view.slots.length === 0 && (
                <tr>
                  <Td colSpan={6} className="text-center text-zinc-500">
                    No timetable slots for this section.
                  </Td>
                </tr>
              )}
              {view.slots.map((s) => {
                const course = courseByOffering[s.course_offering_id];
                return (
                  <tr key={s.id}>
                    <Td>
                      <Badge>{DAY_LABELS[s.day_of_week]}</Badge>
                    </Td>
                    <Td className="font-mono text-xs">
                      {s.start_time.slice(0, 5)} – {s.end_time.slice(0, 5)}
                    </Td>
                    <Td>
                      {course ? (
                        <>
                          <span className="font-mono text-xs">{course.code}</span>{" "}
                          {course.title}
                        </>
                      ) : (
                        <span className="text-zinc-500">—</span>
                      )}
                    </Td>
                    <Td>
                      {s.room_id ? roomById[s.room_id]?.code ?? "?" : (
                        <Badge>online</Badge>
                      )}
                    </Td>
                    <Td className="text-xs text-zinc-500">
                      {s.effective_from} → {s.effective_until}
                    </Td>
                    <Td className="text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => onDelete(s.id)}
                      >
                        Delete
                      </Button>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        </Card>
      )}

      {view && view.exceptions.length > 0 && (
        <Card className="p-3">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            Exceptions
          </p>
          <ul className="space-y-1 text-sm">
            {view.exceptions.map((e) => (
              <li key={e.id}>
                <Badge
                  tone={
                    e.kind === "cancel"
                      ? "red"
                      : e.kind === "room_change"
                        ? "amber"
                        : "neutral"
                  }
                >
                  {e.kind}
                </Badge>{" "}
                {e.exception_date}
                {e.reason ? <span className="text-zinc-500"> — {e.reason}</span> : null}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <AddSlotDialog
        open={open}
        onClose={() => setOpen(false)}
        offerings={offerings ?? []}
        courses={courses ?? []}
        rooms={rooms ?? []}
        onCreated={async () => {
          setOpen(false);
          await loadSection();
        }}
      />
    </div>
  );
}

function AddSlotDialog({
  open,
  onClose,
  offerings,
  courses,
  rooms,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  offerings: CourseOffering[];
  courses: Course[];
  rooms: Room[];
  onCreated: () => Promise<void>;
}) {
  const {
    register,
    handleSubmit,
    watch,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: {
      course_offering_id: "",
      room_id: "",
      day_of_week: 0,
      start_time: "10:00",
      end_time: "11:00",
      effective_from: "",
      effective_until: "",
    },
  });
  const [err, setErr] = useState<string | null>(null);
  const [conflicts, setConflicts] = useState<ConflictItem[] | null>(null);

  useEffect(() => {
    if (open) {
      reset({
        course_offering_id: offerings[0]?.id ?? "",
        room_id: "",
        day_of_week: 0,
        start_time: "10:00",
        end_time: "11:00",
        effective_from: "",
        effective_until: "",
      });
      setErr(null);
      setConflicts(null);
    }
  }, [open, reset, offerings]);

  function offeringLabel(o: CourseOffering): string {
    const c = courses.find((c) => c.id === o.course_id);
    return c ? `${c.code} — ${c.title} (${o.academic_term})` : o.id;
  }

  async function checkConflict(values: FormData): Promise<ConflictResponse | null> {
    const offering = offerings.find((o) => o.id === values.course_offering_id);
    if (!offering) return null;
    return api<ConflictResponse>("/timetable/check-conflict", {
      method: "POST",
      body: {
        room_id: values.room_id || null,
        teacher_user_id: offering.teacher_user_id,
        section_id: offering.section_id,
        day_of_week: values.day_of_week,
        start_time: `${values.start_time}:00`,
        end_time: `${values.end_time}:00`,
        effective_from: values.effective_from,
        effective_until: values.effective_until,
      },
    });
  }

  function bodyFromForm(v: FormData): Record<string, unknown> {
    return {
      course_offering_id: v.course_offering_id,
      room_id: v.room_id || null,
      day_of_week: v.day_of_week,
      start_time: `${v.start_time}:00`,
      end_time: `${v.end_time}:00`,
      effective_from: v.effective_from,
      effective_until: v.effective_until,
    };
  }

  const onSubmit = handleSubmit(async (values) => {
    setErr(null);
    setConflicts(null);
    try {
      const c = await checkConflict(values);
      if (c?.has_conflicts) {
        setConflicts(c.conflicts);
        return;
      }
      await api("/timetable", { method: "POST", body: bodyFromForm(values) });
      await onCreated();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "save failed");
    }
  });

  async function onForce() {
    const values = watch();
    setErr(null);
    try {
      await api("/timetable", {
        method: "POST",
        body: bodyFromForm(values),
        query: { force: true },
      });
      await onCreated();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "save failed");
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Add timetable slot"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          {conflicts && conflicts.length > 0 ? (
            <Button variant="danger" onClick={onForce} disabled={isSubmitting}>
              Save anyway (force)
            </Button>
          ) : (
            <Button onClick={onSubmit} disabled={isSubmitting}>
              {isSubmitting ? "Saving…" : "Save"}
            </Button>
          )}
        </>
      }
    >
      <form onSubmit={onSubmit} className="space-y-3">
        <Field
          label="Course offering"
          error={errors.course_offering_id?.message}
        >
          <Select {...register("course_offering_id")}>
            {offerings.length === 0 && (
              <option value="">No offerings — create one first</option>
            )}
            {offerings.map((o) => (
              <option key={o.id} value={o.id}>
                {offeringLabel(o)}
              </option>
            ))}
          </Select>
        </Field>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Day" error={errors.day_of_week?.message}>
            <Select {...register("day_of_week")}>
              {DAY_LABELS.map((d, i) => (
                <option key={i} value={i}>
                  {d}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Start" error={errors.start_time?.message}>
            <Input type="time" {...register("start_time")} />
          </Field>
          <Field label="End" error={errors.end_time?.message}>
            <Input type="time" {...register("end_time")} />
          </Field>
        </div>
        <div className="grid grid-cols-3 gap-3">
          <Field label="From" error={errors.effective_from?.message}>
            <Input type="date" {...register("effective_from")} />
          </Field>
          <Field label="Until" error={errors.effective_until?.message}>
            <Input type="date" {...register("effective_until")} />
          </Field>
          <Field label="Room (optional)">
            <Select {...register("room_id")}>
              <option value="">Online / TBD</option>
              {rooms.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.code}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        {conflicts && conflicts.length > 0 && (
          <Card className="border-red-200 bg-red-50 p-3">
            <p className="mb-1 text-sm font-medium text-red-700">
              Scheduling conflicts:
            </p>
            <ul className="space-y-1 text-xs text-red-700">
              {conflicts.map((c, i) => (
                <li key={i}>
                  <span className="font-medium uppercase">{c.type}</span> · {c.reason}
                </li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-red-600">
              Click <strong>Save anyway</strong> to override (will be
              audit-logged).
            </p>
          </Card>
        )}
        <ErrorText>{err}</ErrorText>
      </form>
    </Dialog>
  );
}
