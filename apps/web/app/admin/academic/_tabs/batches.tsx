"use client";

import { useEffect, useState } from "react";
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

type Department = { id: string; code: string; name: string };
type Batch = {
  id: string;
  department_id: string;
  name: string;
  admission_year: number;
  program_duration_years: number;
  current_semester: number;
};
type Section = {
  id: string;
  batch_id: string;
  name: string;
  class_teacher_user_id: string | null;
};
type Enrollment = {
  id: number;
  student_user_id: string;
  section_id: string;
  academic_term: string;
};

const batchSchema = z.object({
  department_id: z.string().min(1),
  name: z.string().min(1),
  admission_year: z.coerce.number().int().min(1900).max(2100),
  program_duration_years: z.coerce.number().int().min(1).max(8),
  current_semester: z.coerce.number().int().min(1).max(12),
});
type BatchForm = z.infer<typeof batchSchema>;

const sectionSchema = z.object({
  batch_id: z.string().min(1),
  name: z.string().min(1).max(10),
});
type SectionForm = z.infer<typeof sectionSchema>;

const enrollSchema = z.object({
  student_user_ids_csv: z
    .string()
    .min(1, "paste one or more student UUIDs (comma or newline separated)"),
  academic_term: z.string().min(1),
  semester: z.coerce.number().int().min(1).max(12),
});
type EnrollForm = z.infer<typeof enrollSchema>;

export default function BatchesTab() {
  const [depts, setDepts] = useState<Department[] | null>(null);
  const [batches, setBatches] = useState<Batch[] | null>(null);
  const [sectionsByBatch, setSectionsByBatch] = useState<
    Record<string, Section[]>
  >({});
  const [err, setErr] = useState<string | null>(null);
  const [batchOpen, setBatchOpen] = useState(false);
  const [sectionOpenFor, setSectionOpenFor] = useState<string | null>(null);
  const [enrollOpenFor, setEnrollOpenFor] = useState<Section | null>(null);

  async function load() {
    setErr(null);
    try {
      const [d, b] = await Promise.all([
        api<Page<Department>>("/departments", { query: { limit: 200 } }),
        api<Page<Batch>>("/batches", { query: { limit: 200 } }),
      ]);
      setDepts(d.items);
      setBatches(b.items);
      const sectionMap: Record<string, Section[]> = {};
      for (const batch of b.items) {
        const r = await api<Page<Section>>("/sections", {
          query: { batch_id: batch.id, limit: 50 },
        });
        sectionMap[batch.id] = r.items;
      }
      setSectionsByBatch(sectionMap);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "load failed");
    }
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-zinc-600">
          {batches ? `${batches.length} active batches` : "—"}
        </p>
        <Button
          onClick={() => setBatchOpen(true)}
          disabled={!depts || depts.length === 0}
        >
          Add batch
        </Button>
      </div>

      {err && <ErrorText>{err}</ErrorText>}
      {!batches && !err && <Loading />}

      {batches?.map((b) => {
        const dept = depts?.find((d) => d.id === b.department_id);
        const sections = sectionsByBatch[b.id] ?? [];
        return (
          <Card key={b.id} className="p-4">
            <div className="mb-2 flex items-center justify-between">
              <div>
                <div className="font-medium text-zinc-900">{b.name}</div>
                <div className="text-xs text-zinc-500">
                  {dept?.code ?? "—"} · admitted {b.admission_year} · current
                  sem {b.current_semester}
                </div>
              </div>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setSectionOpenFor(b.id)}
              >
                Add section
              </Button>
            </div>
            <Table>
              <thead>
                <tr>
                  <Th>Section</Th>
                  <Th>Class teacher</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {sections.length === 0 && (
                  <tr>
                    <Td colSpan={3} className="text-center text-zinc-500">
                      No sections.
                    </Td>
                  </tr>
                )}
                {sections.map((s) => (
                  <tr key={s.id}>
                    <Td>
                      <Badge>{`${dept?.code ?? "?"}-${s.name}`}</Badge>
                    </Td>
                    <Td className="font-mono text-xs text-zinc-500">
                      {s.class_teacher_user_id ?? "—"}
                    </Td>
                    <Td className="text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setEnrollOpenFor(s)}
                      >
                        Enroll students
                      </Button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card>
        );
      })}

      <BatchDialog
        open={batchOpen}
        onClose={() => setBatchOpen(false)}
        depts={depts ?? []}
        onCreated={async () => {
          setBatchOpen(false);
          await load();
        }}
      />
      <SectionDialog
        open={sectionOpenFor !== null}
        batchId={sectionOpenFor}
        onClose={() => setSectionOpenFor(null)}
        onCreated={async () => {
          setSectionOpenFor(null);
          await load();
        }}
      />
      <EnrollDialog
        open={enrollOpenFor !== null}
        section={enrollOpenFor}
        onClose={() => setEnrollOpenFor(null)}
        onDone={() => setEnrollOpenFor(null)}
      />
    </div>
  );
}

function BatchDialog({
  open,
  onClose,
  depts,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  depts: Department[];
  onCreated: () => Promise<void>;
}) {
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<BatchForm>({
    resolver: zodResolver(batchSchema),
    defaultValues: {
      department_id: "",
      name: "",
      admission_year: new Date().getFullYear(),
      program_duration_years: 4,
      current_semester: 1,
    },
  });
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      reset({
        department_id: depts[0]?.id ?? "",
        name: "",
        admission_year: new Date().getFullYear(),
        program_duration_years: 4,
        current_semester: 1,
      });
      setErr(null);
    }
  }, [open, reset, depts]);

  const onSubmit = handleSubmit(async (v) => {
    setErr(null);
    try {
      await api("/batches", { method: "POST", body: v });
      await onCreated();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "create failed");
    }
  });

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Add batch"
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
        <Field label="Name" error={errors.name?.message}>
          <Input placeholder="CSE 2024-28" {...register("name")} />
        </Field>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Admission year" error={errors.admission_year?.message}>
            <Input type="number" {...register("admission_year")} />
          </Field>
          <Field
            label="Duration (yrs)"
            error={errors.program_duration_years?.message}
          >
            <Input type="number" {...register("program_duration_years")} />
          </Field>
          <Field
            label="Current sem"
            error={errors.current_semester?.message}
          >
            <Input type="number" {...register("current_semester")} />
          </Field>
        </div>
        <ErrorText>{err}</ErrorText>
      </form>
    </Dialog>
  );
}

function SectionDialog({
  open,
  batchId,
  onClose,
  onCreated,
}: {
  open: boolean;
  batchId: string | null;
  onClose: () => void;
  onCreated: () => Promise<void>;
}) {
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<SectionForm>({
    resolver: zodResolver(sectionSchema),
    defaultValues: { batch_id: "", name: "" },
  });
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (open && batchId) {
      reset({ batch_id: batchId, name: "" });
      setErr(null);
    }
  }, [open, batchId, reset]);

  const onSubmit = handleSubmit(async (v) => {
    setErr(null);
    try {
      await api("/sections", { method: "POST", body: v });
      await onCreated();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "create failed");
    }
  });

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Add section"
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
        <input type="hidden" {...register("batch_id")} />
        <Field label="Section name" error={errors.name?.message}>
          <Input placeholder="A" maxLength={10} {...register("name")} />
        </Field>
        <ErrorText>{err}</ErrorText>
      </form>
    </Dialog>
  );
}

function EnrollDialog({
  open,
  section,
  onClose,
  onDone,
}: {
  open: boolean;
  section: Section | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<EnrollForm>({
    resolver: zodResolver(enrollSchema),
    defaultValues: {
      student_user_ids_csv: "",
      academic_term: "2026-ODD",
      semester: 1,
    },
  });
  const [err, setErr] = useState<string | null>(null);
  const [enrolled, setEnrolled] = useState<Enrollment[] | null>(null);

  useEffect(() => {
    if (open && section) {
      reset({
        student_user_ids_csv: "",
        academic_term: "2026-ODD",
        semester: 1,
      });
      setErr(null);
      setEnrolled(null);
      (async () => {
        try {
          const r = await api<Enrollment[]>(
            `/sections/${section.id}/students`,
          );
          setEnrolled(r);
        } catch (e) {
          setErr(e instanceof ApiError ? e.message : "load failed");
        }
      })();
    }
  }, [open, section, reset]);

  const onSubmit = handleSubmit(async (v) => {
    if (!section) return;
    setErr(null);
    const ids = v.student_user_ids_csv
      .split(/[,\s]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (ids.length === 0) {
      setErr("paste at least one UUID");
      return;
    }
    try {
      await api(`/sections/${section.id}/enrollments`, {
        method: "POST",
        body: {
          student_user_ids: ids,
          academic_term: v.academic_term,
          semester: v.semester,
        },
      });
      onDone();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "enrollment failed");
    }
  });

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={section ? `Enroll students in ${section.name}` : "Enroll students"}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Close
          </Button>
          <Button onClick={onSubmit} disabled={isSubmitting}>
            {isSubmitting ? "Enrolling…" : "Enroll"}
          </Button>
        </>
      }
    >
      <form onSubmit={onSubmit} className="space-y-3">
        <Field
          label="Student UUIDs (comma or newline)"
          error={errors.student_user_ids_csv?.message}
        >
          <textarea
            rows={4}
            className="w-full rounded border border-zinc-300 p-2 font-mono text-xs"
            {...register("student_user_ids_csv")}
          />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Academic term" error={errors.academic_term?.message}>
            <Input {...register("academic_term")} />
          </Field>
          <Field label="Semester" error={errors.semester?.message}>
            <Input type="number" {...register("semester")} />
          </Field>
        </div>
        <ErrorText>{err}</ErrorText>
        {enrolled && (
          <div>
            <p className="mb-1 text-xs font-medium text-zinc-700">
              Currently enrolled ({enrolled.length})
            </p>
            {enrolled.length === 0 ? (
              <p className="text-xs text-zinc-500">none</p>
            ) : (
              <ul className="max-h-32 overflow-y-auto rounded border border-zinc-200 bg-zinc-50 p-2 font-mono text-xs">
                {enrolled.map((e) => (
                  <li key={e.id}>{e.student_user_id}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </form>
    </Dialog>
  );
}
