"use client";

import { useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { ApiError, api, type Page } from "@/lib/api";
import {
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

type Department = { id: string; code: string; name: string };
type Course = {
  id: string;
  department_id: string;
  code: string;
  title: string;
  credits: number;
  semester: number;
  course_type: "theory" | "lab" | "integrated" | "nptel";
};

const COURSE_TYPES = ["theory", "lab", "integrated", "nptel"] as const;
const SEMESTERS = Array.from({ length: 8 }, (_, i) => i + 1);

const schema = z.object({
  department_id: z.string().min(1, "required"),
  code: z.string().min(1, "required"),
  title: z.string().min(1, "required"),
  credits: z.coerce.number().int().min(0).max(12),
  semester: z.coerce.number().int().min(1).max(12),
  course_type: z.enum(COURSE_TYPES),
});
type FormData = z.infer<typeof schema>;

export default function CoursesTab() {
  const [depts, setDepts] = useState<Department[] | null>(null);
  const [courses, setCourses] = useState<Course[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [filterDept, setFilterDept] = useState("");
  const [filterSem, setFilterSem] = useState("");
  const [open, setOpen] = useState(false);

  async function load() {
    setErr(null);
    try {
      const [d, c] = await Promise.all([
        api<Page<Department>>("/departments", { query: { limit: 200 } }),
        api<Page<Course>>("/courses", {
          query: {
            limit: 200,
            department_id: filterDept || undefined,
            semester: filterSem || undefined,
          },
        }),
      ]);
      setDepts(d.items);
      setCourses(c.items);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "load failed");
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterDept, filterSem]);

  const deptByCode = useMemo(() => {
    const m: Record<string, Department> = {};
    (depts ?? []).forEach((d) => (m[d.id] = d));
    return m;
  }, [depts]);

  async function onDelete(id: string) {
    if (!confirm("Soft-delete this course?")) return;
    try {
      await api(`/courses/${id}`, { method: "DELETE" });
      await load();
    } catch (e) {
      alert(e instanceof ApiError ? e.message : "delete failed");
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-48">
          <Field label="Department">
            <Select
              value={filterDept}
              onChange={(e) => setFilterDept(e.target.value)}
            >
              <option value="">All departments</option>
              {(depts ?? []).map((d) => (
                <option key={d.id} value={d.id}>
                  {d.code} — {d.name}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <div className="w-32">
          <Field label="Semester">
            <Select
              value={filterSem}
              onChange={(e) => setFilterSem(e.target.value)}
            >
              <option value="">All</option>
              {SEMESTERS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <div className="ml-auto">
          <Button
            onClick={() => setOpen(true)}
            disabled={!depts || depts.length === 0}
          >
            Add course
          </Button>
        </div>
      </div>

      {err && <ErrorText>{err}</ErrorText>}
      {!courses && !err && <Loading />}
      {courses && (
        <Card>
          <Table>
            <thead>
              <tr>
                <Th>Code</Th>
                <Th>Title</Th>
                <Th>Dept</Th>
                <Th>Sem</Th>
                <Th>Credits</Th>
                <Th>Type</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {courses.length === 0 && (
                <tr>
                  <Td colSpan={7} className="text-center text-zinc-500">
                    No courses match.
                  </Td>
                </tr>
              )}
              {courses.map((c) => (
                <tr key={c.id}>
                  <Td className="font-mono text-xs">{c.code}</Td>
                  <Td>{c.title}</Td>
                  <Td className="text-xs text-zinc-500">
                    {deptByCode[c.department_id]?.code ?? "—"}
                  </Td>
                  <Td>{c.semester}</Td>
                  <Td>{c.credits}</Td>
                  <Td className="capitalize text-zinc-600">{c.course_type}</Td>
                  <Td className="text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => onDelete(c.id)}
                    >
                      Delete
                    </Button>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}

      <CreateDialog
        open={open}
        onClose={() => setOpen(false)}
        depts={depts ?? []}
        defaultDept={filterDept}
        defaultSem={filterSem}
        onCreated={async () => {
          setOpen(false);
          await load();
        }}
      />
    </div>
  );
}

function CreateDialog({
  open,
  onClose,
  depts,
  defaultDept,
  defaultSem,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  depts: Department[];
  defaultDept: string;
  defaultSem: string;
  onCreated: () => Promise<void>;
}) {
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: {
      department_id: defaultDept || depts[0]?.id || "",
      code: "",
      title: "",
      credits: 3,
      semester: defaultSem ? Number(defaultSem) : 1,
      course_type: "theory",
    },
  });
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      reset({
        department_id: defaultDept || depts[0]?.id || "",
        code: "",
        title: "",
        credits: 3,
        semester: defaultSem ? Number(defaultSem) : 1,
        course_type: "theory",
      });
      setErr(null);
    }
  }, [open, reset, defaultDept, defaultSem, depts]);

  const onSubmit = handleSubmit(async (v) => {
    setErr(null);
    try {
      await api("/courses", { method: "POST", body: v });
      await onCreated();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "create failed");
    }
  });

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Add course"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={onSubmit} disabled={isSubmitting}>
            {isSubmitting ? "Saving…" : "Save"}
          </Button>
        </>
      }
    >
      <form onSubmit={onSubmit} className="space-y-3">
        <Field label="Department" error={errors.department_id?.message}>
          <Select {...register("department_id")}>
            {depts.map((d) => (
              <option key={d.id} value={d.id}>
                {d.code} — {d.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Code" error={errors.code?.message}>
          <Input placeholder="CS301" {...register("code")} />
        </Field>
        <Field label="Title" error={errors.title?.message}>
          <Input placeholder="Data Structures" {...register("title")} />
        </Field>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Credits" error={errors.credits?.message}>
            <Input type="number" {...register("credits")} />
          </Field>
          <Field label="Semester" error={errors.semester?.message}>
            <Select {...register("semester")}>
              {SEMESTERS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Type" error={errors.course_type?.message}>
            <Select {...register("course_type")}>
              {COURSE_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <ErrorText>{err}</ErrorText>
      </form>
    </Dialog>
  );
}
