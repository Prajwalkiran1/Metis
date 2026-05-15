"use client";

import { use, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { ApiError, api } from "@/lib/api";
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

type SetupState = "draft" | "published" | "active" | "archived";
type CourseType = "theory" | "lab" | "integrated" | "nptel";

type CourseAssignment = {
  id: string;
  course_id: string;
  course_code: string;
  course_title: string;
  course_type: CourseType;
  section_id: string;
  section_name: string;
  teacher_user_id: string | null;
  teacher_name: string | null;
  parent_offering_id: string | null;
  assessment_scheme_id: string | null;
  is_active: boolean;
};

type ElectiveOption = {
  id: string;
  elective_group_id: string;
  course_id: string;
  course_code: string;
  course_title: string;
  tentative_teacher_id: string | null;
  tentative_teacher_name: string | null;
  is_dissolved: boolean;
};

type ElectiveGroup = {
  id: string;
  semester_setup_id: string;
  name: string;
  description: string | null;
  required_credits: number | null;
  min_enrollment_to_run: number;
  max_enrollment: number | null;
  options: ElectiveOption[];
};

type SemesterSetupDetail = {
  id: string;
  college_id: string;
  department_id: string;
  academic_term_id: string;
  state: SetupState;
  drafted_by_user_id: string;
  published_at: string | null;
  archived_at: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  department_name: string;
  department_code: string;
  academic_term_code: string;
  courses: CourseAssignment[];
  elective_groups: ElectiveGroup[];
};

type Course = {
  id: string;
  code: string;
  title: string;
  course_type: CourseType;
  semester: number;
};

type Section = { id: string; name: string; batch_id: string };
type UserRow = { id: string; name: string; email: string; role: string };

function stateTone(s: SetupState): "neutral" | "green" | "amber" | "red" {
  if (s === "active" || s === "published") return "green";
  if (s === "draft") return "amber";
  return "neutral";
}

function courseTypeTone(t: CourseType): "neutral" | "green" | "amber" | "red" {
  if (t === "integrated") return "green";
  if (t === "lab") return "amber";
  if (t === "nptel") return "red";
  return "neutral";
}

// ── Add-course dialog ──────────────────────────────────────────────────────
const addCourseSchema = z.object({
  course_id: z.string().uuid("pick a course"),
  section_id: z.string().uuid("pick a section"),
  teacher_user_id: z.string().uuid("pick a teacher"),
  parent_offering_id: z.string().uuid().optional().or(z.literal("")),
});
type AddCourseForm = z.infer<typeof addCourseSchema>;

// ── Add-elective-group dialog ──────────────────────────────────────────────
const addEgSchema = z.object({
  name: z.string().min(1).max(100),
  description: z.string().max(2000).optional(),
  required_credits: z.coerce.number().int().min(0).max(12).optional(),
  min_enrollment_to_run: z.coerce.number().int().min(0).max(500).default(5),
  max_enrollment: z.coerce.number().int().min(1).max(1000).optional(),
});
type AddEgForm = z.infer<typeof addEgSchema>;

// ── Add-option dialog ──────────────────────────────────────────────────────
const addOptionSchema = z.object({
  course_id: z.string().uuid("pick a course"),
  tentative_teacher_id: z.string().uuid().optional().or(z.literal("")),
});
type AddOptionForm = z.infer<typeof addOptionSchema>;

export default function SemesterSetupEditorPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const router = useRouter();
  const [setup, setSetup] = useState<SemesterSetupDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [courses, setCourses] = useState<Course[]>([]);
  const [sections, setSections] = useState<Section[]>([]);
  const [teachers, setTeachers] = useState<UserRow[]>([]);
  const [openAddCourse, setOpenAddCourse] = useState(false);
  const [openAddEg, setOpenAddEg] = useState(false);
  const [openAddOption, setOpenAddOption] = useState<string | null>(null);
  const [openPublish, setOpenPublish] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionErr, setActionErr] = useState<string | null>(null);

  const addCourseForm = useForm<AddCourseForm>({
    resolver: zodResolver(addCourseSchema),
    defaultValues: { course_id: "", section_id: "", teacher_user_id: "", parent_offering_id: "" },
  });
  const addEgForm = useForm<AddEgForm>({
    resolver: zodResolver(addEgSchema),
    defaultValues: { name: "", description: "", min_enrollment_to_run: 5 },
  });
  const addOptionForm = useForm<AddOptionForm>({
    resolver: zodResolver(addOptionSchema),
    defaultValues: { course_id: "", tentative_teacher_id: "" },
  });

  const reload = useCallback(async () => {
    try {
      const s = await api<SemesterSetupDetail>(
        `/workflow/semester-setups/${id}`,
      );
      setSetup(s);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "load failed");
    }
  }, [id]);

  useEffect(() => {
    reload();
  }, [reload]);

  useEffect(() => {
    (async () => {
      try {
        const [c, s, t] = await Promise.all([
          api<{ items: Course[]; total: number }>("/courses", {
            query: { limit: 500 },
          }),
          api<{ items: Section[]; total: number }>("/sections", {
            query: { limit: 500 },
          }),
          api<{ items: UserRow[]; total: number }>("/users", {
            query: { role: "teacher", limit: 500 },
          }),
        ]);
        setCourses(c.items);
        setSections(s.items);
        setTeachers(t.items);
      } catch {
        // picker data is best-effort; the dialogs surface their own errors
      }
    })();
  }, []);

  // ── Notes autosave ──
  const notesRef = useRef<string>("");
  useEffect(() => {
    notesRef.current = setup?.notes ?? "";
  }, [setup?.notes]);
  const [notesDraft, setNotesDraft] = useState<string>("");
  const [notesSaving, setNotesSaving] = useState(false);
  useEffect(() => {
    setNotesDraft(setup?.notes ?? "");
  }, [setup?.notes]);

  useEffect(() => {
    if (setup === null || setup.state !== "draft") return;
    if (notesDraft === (setup.notes ?? "")) return;
    const handle = setTimeout(async () => {
      setNotesSaving(true);
      try {
        await api(`/workflow/semester-setups/${id}`, {
          method: "PATCH",
          body: { notes: notesDraft || null },
        });
      } catch {
        // ignore — user retries on next keystroke
      } finally {
        setNotesSaving(false);
      }
    }, 600);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notesDraft, id]);

  const editable = setup?.state === "draft";

  const theoryOfferings = useMemo(
    () =>
      (setup?.courses ?? []).filter(
        (c) => c.course_type === "theory" || c.course_type === "integrated",
      ),
    [setup?.courses],
  );
  const selectedCourseType = useMemo<CourseType | null>(() => {
    const cid = addCourseForm.watch("course_id");
    const c = courses.find((x) => x.id === cid);
    return c ? c.course_type : null;
  }, [addCourseForm.watch("course_id"), courses]);

  // ── Action handlers ──
  async function onAddCourse(values: AddCourseForm) {
    setActionErr(null);
    setBusy("addCourse");
    try {
      await api(`/workflow/semester-setups/${id}/courses`, {
        method: "POST",
        body: {
          course_id: values.course_id,
          section_id: values.section_id,
          teacher_user_id: values.teacher_user_id,
          parent_offering_id: values.parent_offering_id || null,
        },
      });
      setOpenAddCourse(false);
      addCourseForm.reset();
      await reload();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "add failed");
    } finally {
      setBusy(null);
    }
  }

  async function onRemoveCourse(offeringId: string) {
    if (!confirm("Remove this course from the setup?")) return;
    setBusy(`removeCourse:${offeringId}`);
    try {
      await api(
        `/workflow/semester-setups/${id}/courses/${offeringId}`,
        { method: "DELETE" },
      );
      await reload();
    } catch (e) {
      alert(e instanceof ApiError ? e.message : "remove failed");
    } finally {
      setBusy(null);
    }
  }

  async function onAddEg(values: AddEgForm) {
    setActionErr(null);
    setBusy("addEg");
    try {
      await api(`/workflow/semester-setups/${id}/elective-groups`, {
        method: "POST",
        body: {
          name: values.name,
          description: values.description || undefined,
          required_credits: values.required_credits ?? null,
          min_enrollment_to_run: values.min_enrollment_to_run,
          max_enrollment: values.max_enrollment ?? null,
        },
      });
      setOpenAddEg(false);
      addEgForm.reset({ name: "", description: "", min_enrollment_to_run: 5 });
      await reload();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "add failed");
    } finally {
      setBusy(null);
    }
  }

  async function onDeleteEg(egId: string) {
    if (!confirm("Delete this elective group and its options?")) return;
    setBusy(`deleteEg:${egId}`);
    try {
      await api(`/workflow/semester-setups/${id}/elective-groups/${egId}`, {
        method: "DELETE",
      });
      await reload();
    } catch (e) {
      alert(e instanceof ApiError ? e.message : "delete failed");
    } finally {
      setBusy(null);
    }
  }

  async function onAddOption(egId: string, values: AddOptionForm) {
    setActionErr(null);
    setBusy(`addOpt:${egId}`);
    try {
      await api(
        `/workflow/semester-setups/${id}/elective-groups/${egId}/options`,
        {
          method: "POST",
          body: {
            course_id: values.course_id,
            tentative_teacher_id: values.tentative_teacher_id || null,
          },
        },
      );
      setOpenAddOption(null);
      addOptionForm.reset({ course_id: "", tentative_teacher_id: "" });
      await reload();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "add failed");
    } finally {
      setBusy(null);
    }
  }

  async function onDeleteOption(egId: string, optionId: string) {
    if (!confirm("Remove this option?")) return;
    setBusy(`delOpt:${optionId}`);
    try {
      await api(
        `/workflow/semester-setups/${id}/elective-groups/${egId}/options/${optionId}`,
        { method: "DELETE" },
      );
      await reload();
    } catch (e) {
      alert(e instanceof ApiError ? e.message : "delete failed");
    } finally {
      setBusy(null);
    }
  }

  async function onPublish() {
    setBusy("publish");
    setActionErr(null);
    try {
      await api(`/workflow/semester-setups/${id}/publish`, { method: "POST" });
      setOpenPublish(false);
      router.push("/hod/dashboard");
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "publish failed");
    } finally {
      setBusy(null);
    }
  }

  if (err) return <ErrorText>{err}</ErrorText>;
  if (!setup) return <Loading />;

  const publishBlockedReason = (() => {
    if (!editable) return "Only drafts can be published.";
    if (setup.courses.length === 0)
      return "Add at least one course before publishing.";
    if (setup.courses.some((c) => !c.teacher_user_id))
      return "Every course must have a tentative teacher.";
    return null;
  })();

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold text-zinc-900">
            Semester setup · {setup.academic_term_code}
          </h1>
          <p className="text-sm text-zinc-500">
            {setup.department_name} ({setup.department_code})
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Badge tone={stateTone(setup.state)}>{setup.state}</Badge>
          <Button
            disabled={publishBlockedReason !== null}
            title={publishBlockedReason ?? undefined}
            onClick={() => {
              setActionErr(null);
              setOpenPublish(true);
            }}
          >
            Publish
          </Button>
        </div>
      </div>

      <Card className="p-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-zinc-900">Notes</h2>
          <span className="text-xs text-zinc-500">
            {editable ? (notesSaving ? "Saving…" : "Autosaved") : "Read-only"}
          </span>
        </div>
        <textarea
          className="mt-2 w-full rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-zinc-900 disabled:bg-zinc-50"
          rows={3}
          value={notesDraft}
          disabled={!editable}
          onChange={(e) => setNotesDraft(e.target.value)}
        />
      </Card>

      <Card className="overflow-x-auto">
        <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-3">
          <h2 className="text-sm font-semibold text-zinc-900">
            Courses ({setup.courses.length})
          </h2>
          {editable ? (
            <Button onClick={() => setOpenAddCourse(true)}>Add course</Button>
          ) : null}
        </div>
        {setup.courses.length === 0 ? (
          <p className="px-4 py-6 text-sm text-zinc-500">
            No courses assigned yet.
          </p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Course</Th>
                <Th>Type</Th>
                <Th>Section</Th>
                <Th>Teacher</Th>
                <Th>Parent</Th>
                <Th>Scheme</Th>
                {editable ? <Th></Th> : null}
              </tr>
            </thead>
            <tbody>
              {setup.courses.map((c) => (
                <tr key={c.id}>
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
                  <Td className="text-zinc-700">
                    {c.teacher_name ?? "—"}
                  </Td>
                  <Td className="text-zinc-500">
                    {c.parent_offering_id
                      ? setup.courses.find((x) => x.id === c.parent_offering_id)
                          ?.course_code ?? "—"
                      : "—"}
                  </Td>
                  <Td className="text-zinc-500">
                    {c.assessment_scheme_id ? "linked" : "—"}
                  </Td>
                  {editable ? (
                    <Td>
                      <button
                        type="button"
                        className="text-xs text-red-600 hover:underline"
                        onClick={() => onRemoveCourse(c.id)}
                        disabled={busy === `removeCourse:${c.id}`}
                      >
                        Remove
                      </button>
                    </Td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <Card className="overflow-x-auto">
        <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-3">
          <h2 className="text-sm font-semibold text-zinc-900">
            Elective groups ({setup.elective_groups.length})
          </h2>
          {editable ? (
            <Button onClick={() => setOpenAddEg(true)}>Add group</Button>
          ) : null}
        </div>
        {setup.elective_groups.length === 0 ? (
          <p className="px-4 py-6 text-sm text-zinc-500">
            No elective groups yet.
          </p>
        ) : (
          <div className="space-y-4 p-4">
            {setup.elective_groups.map((eg) => (
              <div
                key={eg.id}
                className="rounded border border-zinc-200 bg-white"
              >
                <div className="flex items-center justify-between border-b border-zinc-100 px-3 py-2">
                  <div>
                    <div className="text-sm font-medium text-zinc-900">
                      {eg.name}
                    </div>
                    <div className="text-xs text-zinc-500">
                      min {eg.min_enrollment_to_run}
                      {eg.max_enrollment ? ` · max ${eg.max_enrollment}` : ""}
                      {eg.required_credits != null
                        ? ` · ${eg.required_credits} credits`
                        : ""}
                    </div>
                  </div>
                  {editable ? (
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => {
                          addOptionForm.reset({
                            course_id: "",
                            tentative_teacher_id: "",
                          });
                          setOpenAddOption(eg.id);
                        }}
                      >
                        Add option
                      </Button>
                      <Button
                        size="sm"
                        variant="danger"
                        onClick={() => onDeleteEg(eg.id)}
                        disabled={busy === `deleteEg:${eg.id}`}
                      >
                        Delete
                      </Button>
                    </div>
                  ) : null}
                </div>
                {eg.options.length === 0 ? (
                  <p className="px-3 py-3 text-sm text-zinc-500">
                    No options yet.
                  </p>
                ) : (
                  <Table>
                    <thead>
                      <tr>
                        <Th>Course</Th>
                        <Th>Tentative teacher</Th>
                        {editable ? <Th></Th> : null}
                      </tr>
                    </thead>
                    <tbody>
                      {eg.options.map((o) => (
                        <tr key={o.id}>
                          <Td>
                            <div className="font-medium">{o.course_code}</div>
                            <div className="text-xs text-zinc-500">
                              {o.course_title}
                            </div>
                          </Td>
                          <Td className="text-zinc-700">
                            {o.tentative_teacher_name ?? "—"}
                          </Td>
                          {editable ? (
                            <Td>
                              <button
                                type="button"
                                className="text-xs text-red-600 hover:underline"
                                onClick={() => onDeleteOption(eg.id, o.id)}
                                disabled={busy === `delOpt:${o.id}`}
                              >
                                Remove
                              </button>
                            </Td>
                          ) : null}
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* ── Add-course dialog ───────────────────────────────────────────── */}
      <Dialog
        open={openAddCourse}
        onClose={() => setOpenAddCourse(false)}
        title="Add course to setup"
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => setOpenAddCourse(false)}
              disabled={busy === "addCourse"}
            >
              Cancel
            </Button>
            <Button
              onClick={addCourseForm.handleSubmit(onAddCourse)}
              disabled={busy === "addCourse"}
            >
              {busy === "addCourse" ? "Adding…" : "Add"}
            </Button>
          </>
        }
      >
        <form
          className="space-y-3"
          onSubmit={addCourseForm.handleSubmit(onAddCourse)}
        >
          <Field
            label="Course"
            error={addCourseForm.formState.errors.course_id?.message}
          >
            <Select {...addCourseForm.register("course_id")}>
              <option value="">— select —</option>
              {courses.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.code} — {c.title} [{c.course_type}]
                </option>
              ))}
            </Select>
          </Field>
          {selectedCourseType ? (
            <div className="text-xs text-zinc-500">
              Type:{" "}
              <Badge tone={courseTypeTone(selectedCourseType)}>
                {selectedCourseType}
              </Badge>
              {selectedCourseType === "lab" ? (
                <span className="ml-2">
                  Pair with a theory offering below if this is the lab half of
                  an integrated course.
                </span>
              ) : null}
            </div>
          ) : null}
          <Field
            label="Section"
            error={addCourseForm.formState.errors.section_id?.message}
          >
            <Select {...addCourseForm.register("section_id")}>
              <option value="">— select —</option>
              {sections.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field
            label="Tentative teacher"
            error={addCourseForm.formState.errors.teacher_user_id?.message}
          >
            <Select {...addCourseForm.register("teacher_user_id")}>
              <option value="">— select —</option>
              {teachers.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name} ({t.email})
                </option>
              ))}
            </Select>
          </Field>
          {selectedCourseType === "lab" ? (
            <Field label="Parent theory offering (optional)">
              <Select {...addCourseForm.register("parent_offering_id")}>
                <option value="">— none —</option>
                {theoryOfferings.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.course_code} — {o.course_title} ({o.section_name})
                  </option>
                ))}
              </Select>
            </Field>
          ) : null}
          {actionErr ? <ErrorText>{actionErr}</ErrorText> : null}
        </form>
      </Dialog>

      {/* ── Add-elective-group dialog ───────────────────────────────────── */}
      <Dialog
        open={openAddEg}
        onClose={() => setOpenAddEg(false)}
        title="Add elective group"
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => setOpenAddEg(false)}
              disabled={busy === "addEg"}
            >
              Cancel
            </Button>
            <Button
              onClick={addEgForm.handleSubmit(onAddEg)}
              disabled={busy === "addEg"}
            >
              {busy === "addEg" ? "Adding…" : "Add"}
            </Button>
          </>
        }
      >
        <form
          className="space-y-3"
          onSubmit={addEgForm.handleSubmit(onAddEg)}
        >
          <Field
            label="Name"
            error={addEgForm.formState.errors.name?.message}
          >
            <Input {...addEgForm.register("name")} />
          </Field>
          <Field label="Description (optional)">
            <textarea
              className="w-full rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-zinc-900"
              rows={2}
              {...addEgForm.register("description")}
            />
          </Field>
          <div className="grid grid-cols-3 gap-2">
            <Field label="Required credits">
              <Input
                type="number"
                min={0}
                max={12}
                {...addEgForm.register("required_credits")}
              />
            </Field>
            <Field label="Min to run">
              <Input
                type="number"
                min={0}
                max={500}
                {...addEgForm.register("min_enrollment_to_run")}
              />
            </Field>
            <Field label="Max cap">
              <Input
                type="number"
                min={1}
                max={1000}
                {...addEgForm.register("max_enrollment")}
              />
            </Field>
          </div>
          {actionErr ? <ErrorText>{actionErr}</ErrorText> : null}
        </form>
      </Dialog>

      {/* ── Add-option dialog ───────────────────────────────────────────── */}
      <Dialog
        open={openAddOption !== null}
        onClose={() => setOpenAddOption(null)}
        title="Add option"
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => setOpenAddOption(null)}
              disabled={busy?.startsWith("addOpt:")}
            >
              Cancel
            </Button>
            <Button
              onClick={addOptionForm.handleSubmit((v) =>
                openAddOption ? onAddOption(openAddOption, v) : undefined,
              )}
              disabled={busy?.startsWith("addOpt:")}
            >
              {busy?.startsWith("addOpt:") ? "Adding…" : "Add"}
            </Button>
          </>
        }
      >
        <form
          className="space-y-3"
          onSubmit={addOptionForm.handleSubmit((v) =>
            openAddOption ? onAddOption(openAddOption, v) : undefined,
          )}
        >
          <Field
            label="Course"
            error={addOptionForm.formState.errors.course_id?.message}
          >
            <Select {...addOptionForm.register("course_id")}>
              <option value="">— select —</option>
              {courses.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.code} — {c.title} [{c.course_type}]
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Tentative teacher (optional)">
            <Select {...addOptionForm.register("tentative_teacher_id")}>
              <option value="">— none —</option>
              {teachers.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name} ({t.email})
                </option>
              ))}
            </Select>
          </Field>
          {actionErr ? <ErrorText>{actionErr}</ErrorText> : null}
        </form>
      </Dialog>

      {/* ── Publish confirm dialog ──────────────────────────────────────── */}
      <Dialog
        open={openPublish}
        onClose={() => setOpenPublish(false)}
        title="Publish semester setup"
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => setOpenPublish(false)}
              disabled={busy === "publish"}
            >
              Cancel
            </Button>
            <Button
              onClick={onPublish}
              disabled={busy === "publish"}
            >
              {busy === "publish" ? "Publishing…" : "Publish"}
            </Button>
          </>
        }
      >
        <p className="text-sm text-zinc-700">
          You are about to publish the {setup.academic_term_code} setup for{" "}
          {setup.department_name}. This locks the structure (no more edits),
          marks the setup as active for students and teachers, and notifies
          college admins.
        </p>
        <ul className="list-disc pl-5 text-xs text-zinc-500">
          <li>{setup.courses.length} courses assigned</li>
          <li>{setup.elective_groups.length} elective groups</li>
        </ul>
        {actionErr ? <ErrorText>{actionErr}</ErrorText> : null}
      </Dialog>
    </div>
  );
}
