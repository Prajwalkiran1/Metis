"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
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

type SemesterSetupList = {
  id: string;
  state: SetupState;
  academic_term_id: string;
  registration_opens_at: string | null;
  registration_closes_at: string | null;
};

type ElectiveGroupShallow = {
  id: string;
  semester_setup_id: string;
  name: string;
  min_enrollment_to_run: number;
  max_enrollment: number | null;
};

type SemesterSetupDetail = {
  id: string;
  academic_term_id: string;
  state: SetupState;
  registration_opens_at: string | null;
  registration_closes_at: string | null;
  elective_groups: ElectiveGroupShallow[];
};

type StudentMini = {
  student_user_id: string;
  name: string;
  usn: string | null;
  registered_at: string;
};

type OptionEnrollment = {
  option_id: string;
  course_id: string;
  course_code: string;
  course_title: string;
  tentative_teacher_id: string | null;
  tentative_teacher_name: string | null;
  is_dissolved: boolean;
  current_enrollment: number;
  status: "under_subscribed" | "over_subscribed" | "healthy";
  students: StudentMini[];
};

type EnrollmentView = {
  elective_group_id: string;
  semester_setup_id: string;
  name: string;
  min_enrollment_to_run: number;
  max_enrollment: number | null;
  options: OptionEnrollment[];
};

type CascadeSummary = {
  students_migrated: number;
  attendance_records_preserved: number;
  marks_preserved: number;
  lab_batch_memberships_removed: number;
  enrollment_rows_mutated: number;
  affected_offering_ids: string[];
  per_student: { student_id: string; skipped?: string }[];
};

type DisplacedStudent = StudentMini;

function statusTone(
  s: "under_subscribed" | "over_subscribed" | "healthy",
): "amber" | "red" | "green" {
  if (s === "under_subscribed") return "amber";
  if (s === "over_subscribed") return "red";
  return "green";
}

const windowSchema = z
  .object({
    opens_at: z.string().min(1),
    closes_at: z.string().min(1),
  })
  .refine((d) => new Date(d.closes_at) > new Date(d.opens_at), {
    message: "closes_at must be after opens_at",
    path: ["closes_at"],
  });
type WindowForm = z.infer<typeof windowSchema>;

const dissolveSchema = z.object({
  target_option_id: z.string().uuid(),
  reason: z.string().min(1).max(2000),
  confirm: z.string().min(1),
});
type DissolveForm = z.infer<typeof dissolveSchema>;

const capSchema = z.object({
  max_enrollment: z.coerce.number().int().min(1).max(1000),
  redistribute_to_option_id: z.string().uuid().optional().or(z.literal("")),
  redistribute_strategy: z
    .enum(["by_registration_order", "manual"])
    .optional()
    .or(z.literal("")),
});
type CapForm = z.infer<typeof capSchema>;

const migrateSchema = z.object({
  student_id: z.string().uuid(),
  from_option_id: z.string().uuid(),
  to_option_id: z.string().uuid(),
  reason: z.string().min(1).max(2000),
});
type MigrateForm = z.infer<typeof migrateSchema>;

function isoLocalToZ(s: string | null | undefined): string | null {
  // <input type="datetime-local"> returns "YYYY-MM-DDTHH:mm" with no Z.
  if (!s) return null;
  return new Date(s).toISOString();
}

export default function HodElectivesPage() {
  const [setups, setSetups] = useState<SemesterSetupList[] | null>(null);
  const [setupId, setSetupId] = useState<string>("");
  const [setupDetail, setSetupDetail] = useState<SemesterSetupDetail | null>(null);
  const [egId, setEgId] = useState<string>("");
  const [enrollment, setEnrollment] = useState<EnrollmentView | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [openWindow, setOpenWindow] = useState(false);
  const [openDissolve, setOpenDissolve] = useState<OptionEnrollment | null>(
    null,
  );
  const [previewSummary, setPreviewSummary] = useState<CascadeSummary | null>(
    null,
  );
  const [openCap, setOpenCap] = useState<OptionEnrollment | null>(null);
  const [displaced, setDisplaced] = useState<DisplacedStudent[] | null>(null);
  const [openMigrate, setOpenMigrate] = useState(false);

  const windowForm = useForm<WindowForm>({
    resolver: zodResolver(windowSchema),
    defaultValues: { opens_at: "", closes_at: "" },
  });
  const dissolveForm = useForm<DissolveForm>({
    resolver: zodResolver(dissolveSchema),
    defaultValues: { target_option_id: "", reason: "", confirm: "" },
  });
  const capForm = useForm<CapForm>({
    resolver: zodResolver(capSchema),
    defaultValues: {
      max_enrollment: 30,
      redistribute_to_option_id: "",
      redistribute_strategy: "",
    },
  });
  const migrateForm = useForm<MigrateForm>({
    resolver: zodResolver(migrateSchema),
    defaultValues: {
      student_id: "",
      from_option_id: "",
      to_option_id: "",
      reason: "",
    },
  });

  // ── data loaders ──
  const reloadSetups = useCallback(async () => {
    try {
      const all = await api<SemesterSetupList[]>("/workflow/semester-setups");
      const usable = all.filter((s) => s.state !== "draft");
      setSetups(usable);
      if (usable.length > 0 && !setupId) setSetupId(usable[0].id);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "load failed");
    }
  }, [setupId]);

  const reloadSetupDetail = useCallback(async () => {
    if (!setupId) return;
    try {
      const d = await api<SemesterSetupDetail>(
        `/workflow/semester-setups/${setupId}`,
      );
      setSetupDetail(d);
      if (d.elective_groups.length > 0 && !egId) {
        setEgId(d.elective_groups[0].id);
      }
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "load failed");
    }
  }, [setupId, egId]);

  const reloadEnrollment = useCallback(async () => {
    if (!egId) return;
    try {
      const v = await api<EnrollmentView>(
        `/workflow/elective-groups/${egId}/enrollment`,
      );
      setEnrollment(v);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "load failed");
    }
  }, [egId]);

  useEffect(() => {
    reloadSetups();
  }, [reloadSetups]);
  useEffect(() => {
    reloadSetupDetail();
  }, [reloadSetupDetail]);
  useEffect(() => {
    reloadEnrollment();
  }, [reloadEnrollment]);

  // ── window save ──
  async function onSaveWindow(values: WindowForm) {
    if (!setupId) return;
    setBusy("window");
    setActionErr(null);
    try {
      await api(`/workflow/semester-setups/${setupId}/registration-window`, {
        method: "POST",
        body: {
          opens_at: isoLocalToZ(values.opens_at),
          closes_at: isoLocalToZ(values.closes_at),
        },
      });
      setOpenWindow(false);
      await reloadSetupDetail();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "save failed");
    } finally {
      setBusy(null);
    }
  }

  // ── dissolve ──
  async function onPreviewDissolve(values: DissolveForm) {
    if (!egId || !openDissolve) return;
    setBusy("preview");
    setActionErr(null);
    try {
      const summary = await api<CascadeSummary>(
        `/workflow/elective-groups/${egId}/options/${openDissolve.option_id}/dissolve/preview`,
        {
          method: "POST",
          body: {
            target_option_id: values.target_option_id,
            reason: values.reason || "preview",
          },
        },
      );
      setPreviewSummary(summary);
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "preview failed");
    } finally {
      setBusy(null);
    }
  }

  async function onConfirmDissolve(values: DissolveForm) {
    if (!egId || !openDissolve) return;
    if (values.confirm !== openDissolve.course_code) {
      setActionErr("type the source course code exactly to confirm");
      return;
    }
    setBusy("dissolve");
    setActionErr(null);
    try {
      await api(
        `/workflow/elective-groups/${egId}/options/${openDissolve.option_id}/dissolve`,
        {
          method: "POST",
          body: {
            target_option_id: values.target_option_id,
            reason: values.reason,
          },
        },
      );
      setOpenDissolve(null);
      setPreviewSummary(null);
      dissolveForm.reset();
      await reloadEnrollment();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "dissolve failed");
    } finally {
      setBusy(null);
    }
  }

  // ── cap ──
  async function onCap(values: CapForm) {
    if (!egId || !openCap) return;
    setBusy("cap");
    setActionErr(null);
    try {
      const r = await api<{
        new_max: number;
        displaced: DisplacedStudent[];
        summary: CascadeSummary | null;
      }>(`/workflow/elective-groups/${egId}/options/${openCap.option_id}/cap`, {
        method: "POST",
        body: {
          max_enrollment: values.max_enrollment,
          redistribute_to_option_id:
            values.redistribute_to_option_id || undefined,
          redistribute_strategy: values.redistribute_strategy || undefined,
        },
      });
      if (r.displaced && r.displaced.length > 0 && !r.summary) {
        setDisplaced(r.displaced);
      } else {
        setOpenCap(null);
        setDisplaced(null);
        capForm.reset({
          max_enrollment: 30,
          redistribute_to_option_id: "",
          redistribute_strategy: "",
        });
        await reloadEnrollment();
      }
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "cap failed");
    } finally {
      setBusy(null);
    }
  }

  // ── manual migrate ──
  async function onManualMigrate(values: MigrateForm) {
    if (!egId) return;
    setBusy("migrate");
    setActionErr(null);
    try {
      await api(`/workflow/elective-groups/${egId}/migrate-student`, {
        method: "POST",
        body: values,
      });
      setOpenMigrate(false);
      migrateForm.reset();
      await reloadEnrollment();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "migrate failed");
    } finally {
      setBusy(null);
    }
  }

  if (err) return <ErrorText>{err}</ErrorText>;
  if (setups === null) return <Loading />;

  if (setups.length === 0) {
    return (
      <Card className="p-4 text-sm text-zinc-600">
        No published semester setups for your department yet. Publish one
        from <a className="underline" href="/hod/semester-setup">Semester setup</a>{" "}
        first.
      </Card>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-lg font-semibold text-zinc-900">Electives</h1>
          <p className="text-sm text-zinc-500">
            Set registration windows, watch enrolment, dissolve under-subscribed
            options, redistribute when an option is over capacity.
          </p>
        </div>
        <div className="flex gap-2 text-sm">
          <a
            href="/hod/lab-batches"
            className="text-zinc-700 underline hover:text-zinc-900"
          >
            Lab batches →
          </a>
          <a
            href="/hod/scheme-templates"
            className="text-zinc-700 underline hover:text-zinc-900"
          >
            Scheme templates →
          </a>
        </div>
      </div>

      <Card className="p-3">
        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1">
            <label className="block text-xs font-medium text-zinc-700">
              Setup
            </label>
            <Select
              value={setupId}
              onChange={(e) => {
                setSetupId(e.target.value);
                setEgId("");
                setEnrollment(null);
              }}
            >
              {setups.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.academic_term_id.slice(0, 8)}… [{s.state}]
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1">
            <label className="block text-xs font-medium text-zinc-700">
              Elective group
            </label>
            <Select
              value={egId}
              onChange={(e) => setEgId(e.target.value)}
              disabled={!setupDetail || setupDetail.elective_groups.length === 0}
            >
              {(setupDetail?.elective_groups ?? []).map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </Select>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <Button
              variant="secondary"
              onClick={() => {
                windowForm.reset({
                  opens_at: setupDetail?.registration_opens_at
                    ? setupDetail.registration_opens_at.slice(0, 16)
                    : "",
                  closes_at: setupDetail?.registration_closes_at
                    ? setupDetail.registration_closes_at.slice(0, 16)
                    : "",
                });
                setActionErr(null);
                setOpenWindow(true);
              }}
              disabled={!setupId}
            >
              Set window
            </Button>
            <Button
              variant="secondary"
              onClick={() => {
                migrateForm.reset({
                  student_id: "",
                  from_option_id: "",
                  to_option_id: "",
                  reason: "",
                });
                setActionErr(null);
                setOpenMigrate(true);
              }}
              disabled={!enrollment}
            >
              Manual migrate
            </Button>
          </div>
        </div>
        {setupDetail ? (
          <p className="mt-2 text-xs text-zinc-500">
            Window:{" "}
            {setupDetail.registration_opens_at
              ? `${new Date(setupDetail.registration_opens_at).toLocaleString()} → ${new Date(setupDetail.registration_closes_at!).toLocaleString()}`
              : "not set"}
          </p>
        ) : null}
      </Card>

      {enrollment ? (
        <Card className="overflow-x-auto">
          <div className="border-b border-zinc-200 px-4 py-3 text-sm font-semibold text-zinc-900">
            {enrollment.name}
            <span className="ml-2 text-xs font-normal text-zinc-500">
              min {enrollment.min_enrollment_to_run} to run
            </span>
          </div>
          {enrollment.options.length === 0 ? (
            <p className="px-4 py-6 text-sm text-zinc-500">
              No options in this group.
            </p>
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Course</Th>
                  <Th>Teacher</Th>
                  <Th>Enrolled</Th>
                  <Th>Status</Th>
                  <Th>Cap</Th>
                  <Th></Th>
                </tr>
              </thead>
              <tbody>
                {enrollment.options.map((o) => (
                  <tr key={o.option_id}>
                    <Td>
                      <div className="font-medium">{o.course_code}</div>
                      <div className="text-xs text-zinc-500">
                        {o.course_title}
                      </div>
                    </Td>
                    <Td>{o.tentative_teacher_name ?? "—"}</Td>
                    <Td>{o.current_enrollment}</Td>
                    <Td>
                      {o.is_dissolved ? (
                        <Badge tone="red">dissolved</Badge>
                      ) : (
                        <Badge tone={statusTone(o.status)}>{o.status}</Badge>
                      )}
                    </Td>
                    <Td className="text-zinc-600">—</Td>
                    <Td className="space-x-2 whitespace-nowrap">
                      <button
                        type="button"
                        className="text-xs text-zinc-900 underline"
                        onClick={() => {
                          capForm.reset({
                            max_enrollment: Math.max(
                              1,
                              o.current_enrollment,
                            ),
                            redistribute_to_option_id: "",
                            redistribute_strategy: "",
                          });
                          setActionErr(null);
                          setDisplaced(null);
                          setOpenCap(o);
                        }}
                        disabled={o.is_dissolved}
                      >
                        Cap
                      </button>
                      <button
                        type="button"
                        className="text-xs text-red-600 underline"
                        onClick={() => {
                          dissolveForm.reset({
                            target_option_id: "",
                            reason: "",
                            confirm: "",
                          });
                          setActionErr(null);
                          setPreviewSummary(null);
                          setOpenDissolve(o);
                        }}
                        disabled={o.is_dissolved}
                      >
                        Dissolve
                      </button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
      ) : (
        <Loading />
      )}

      {/* Per-option student lists */}
      {enrollment ? (
        <div className="space-y-4">
          {enrollment.options.map((o) => (
            <Card key={`students-${o.option_id}`} className="overflow-x-auto">
              <div className="border-b border-zinc-200 px-4 py-2 text-xs text-zinc-600">
                {o.course_code} students ({o.students.length})
              </div>
              {o.students.length === 0 ? (
                <p className="px-4 py-3 text-sm text-zinc-500">No registrants.</p>
              ) : (
                <Table>
                  <thead>
                    <tr>
                      <Th>USN</Th>
                      <Th>Name</Th>
                      <Th>Registered at</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {o.students.map((s) => (
                      <tr key={s.student_user_id}>
                        <Td className="font-mono text-xs">{s.usn ?? "—"}</Td>
                        <Td>{s.name}</Td>
                        <Td className="text-zinc-600">
                          {new Date(s.registered_at).toLocaleString()}
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
            </Card>
          ))}
        </div>
      ) : null}

      {/* ── Window dialog ── */}
      <Dialog
        open={openWindow}
        onClose={() => setOpenWindow(false)}
        title="Registration window"
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => setOpenWindow(false)}
              disabled={busy === "window"}
            >
              Cancel
            </Button>
            <Button
              onClick={windowForm.handleSubmit(onSaveWindow)}
              disabled={busy === "window"}
            >
              {busy === "window" ? "Saving…" : "Save"}
            </Button>
          </>
        }
      >
        <form
          className="space-y-3"
          onSubmit={windowForm.handleSubmit(onSaveWindow)}
        >
          <Field
            label="Opens at"
            error={windowForm.formState.errors.opens_at?.message}
          >
            <Input type="datetime-local" {...windowForm.register("opens_at")} />
          </Field>
          <Field
            label="Closes at"
            error={windowForm.formState.errors.closes_at?.message}
          >
            <Input type="datetime-local" {...windowForm.register("closes_at")} />
          </Field>
          {actionErr ? <ErrorText>{actionErr}</ErrorText> : null}
        </form>
      </Dialog>

      {/* ── Dissolve dialog ── */}
      <Dialog
        open={openDissolve !== null}
        onClose={() => {
          setOpenDissolve(null);
          setPreviewSummary(null);
        }}
        title={`Dissolve ${openDissolve?.course_code ?? ""}`}
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => {
                setOpenDissolve(null);
                setPreviewSummary(null);
              }}
              disabled={busy === "dissolve"}
            >
              Cancel
            </Button>
            <Button
              variant="secondary"
              onClick={dissolveForm.handleSubmit(onPreviewDissolve)}
              disabled={busy !== null}
            >
              Preview
            </Button>
            <Button
              variant="danger"
              onClick={dissolveForm.handleSubmit(onConfirmDissolve)}
              disabled={
                busy === "dissolve" ||
                previewSummary === null ||
                dissolveForm.watch("confirm") !==
                  (openDissolve?.course_code ?? "")
              }
            >
              {busy === "dissolve" ? "Dissolving…" : "Confirm dissolution"}
            </Button>
          </>
        }
      >
        <form className="space-y-3" onSubmit={(e) => e.preventDefault()}>
          <Field
            label="Migrate students to"
            error={dissolveForm.formState.errors.target_option_id?.message}
          >
            <Select {...dissolveForm.register("target_option_id")}>
              <option value="">— select —</option>
              {(enrollment?.options ?? [])
                .filter(
                  (o) =>
                    o.option_id !== openDissolve?.option_id && !o.is_dissolved,
                )
                .map((o) => (
                  <option key={o.option_id} value={o.option_id}>
                    {o.course_code} — {o.course_title}
                  </option>
                ))}
            </Select>
          </Field>
          <Field
            label="Reason"
            error={dissolveForm.formState.errors.reason?.message}
          >
            <Input {...dissolveForm.register("reason")} placeholder="e.g. low enrolment" />
          </Field>
          {previewSummary ? (
            <Card className="border-amber-300 bg-amber-50 p-3">
              <p className="text-xs font-semibold text-amber-900">
                Blast radius
              </p>
              <ul className="mt-1 list-disc pl-5 text-xs text-amber-900">
                <li>{previewSummary.students_migrated} students migrated</li>
                <li>
                  {previewSummary.attendance_records_preserved} attendance
                  records preserved (history)
                </li>
                <li>{previewSummary.marks_preserved} marks preserved</li>
                <li>
                  {previewSummary.lab_batch_memberships_removed} lab batch
                  memberships removed
                </li>
                <li>
                  {previewSummary.enrollment_rows_mutated} section enrollment
                  rows mutated
                </li>
              </ul>
            </Card>
          ) : null}
          <Field
            label={`Type "${openDissolve?.course_code ?? ""}" to confirm`}
            error={dissolveForm.formState.errors.confirm?.message}
          >
            <Input {...dissolveForm.register("confirm")} />
          </Field>
          {actionErr ? <ErrorText>{actionErr}</ErrorText> : null}
        </form>
      </Dialog>

      {/* ── Cap dialog ── */}
      <Dialog
        open={openCap !== null}
        onClose={() => {
          setOpenCap(null);
          setDisplaced(null);
        }}
        title={`Cap capacity — ${openCap?.course_code ?? ""}`}
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => {
                setOpenCap(null);
                setDisplaced(null);
              }}
              disabled={busy === "cap"}
            >
              Cancel
            </Button>
            <Button
              onClick={capForm.handleSubmit(onCap)}
              disabled={busy === "cap"}
            >
              {busy === "cap" ? "Saving…" : "Save"}
            </Button>
          </>
        }
      >
        <form className="space-y-3" onSubmit={capForm.handleSubmit(onCap)}>
          <Field
            label="Max enrollment"
            error={capForm.formState.errors.max_enrollment?.message}
          >
            <Input
              type="number"
              min={1}
              max={1000}
              {...capForm.register("max_enrollment")}
            />
          </Field>
          <Field label="Redistribute overflow to (optional)">
            <Select {...capForm.register("redistribute_to_option_id")}>
              <option value="">— none —</option>
              {(enrollment?.options ?? [])
                .filter(
                  (o) =>
                    o.option_id !== openCap?.option_id && !o.is_dissolved,
                )
                .map((o) => (
                  <option key={o.option_id} value={o.option_id}>
                    {o.course_code} — {o.course_title}
                  </option>
                ))}
            </Select>
          </Field>
          <Field label="Strategy">
            <Select {...capForm.register("redistribute_strategy")}>
              <option value="">— none —</option>
              <option value="by_registration_order">
                by_registration_order (latest displaced)
              </option>
              <option value="manual">manual (return displaced list)</option>
            </Select>
          </Field>
          {displaced ? (
            <Card className="border-amber-300 bg-amber-50 p-3">
              <p className="text-xs font-semibold text-amber-900">
                {displaced.length} student(s) would be displaced
              </p>
              <ul className="mt-1 list-disc pl-5 text-xs text-amber-900">
                {displaced.slice(0, 5).map((d) => (
                  <li key={d.student_user_id}>
                    {d.usn ? `${d.usn} · ` : ""}
                    {d.name}
                  </li>
                ))}
                {displaced.length > 5 ? (
                  <li>… {displaced.length - 5} more</li>
                ) : null}
              </ul>
              <p className="mt-2 text-xs text-amber-900">
                Cap saved. Use Manual migrate to move them individually.
              </p>
            </Card>
          ) : null}
          {actionErr ? <ErrorText>{actionErr}</ErrorText> : null}
        </form>
      </Dialog>

      {/* ── Manual migrate dialog ── */}
      <Dialog
        open={openMigrate}
        onClose={() => setOpenMigrate(false)}
        title="Manual student migration"
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => setOpenMigrate(false)}
              disabled={busy === "migrate"}
            >
              Cancel
            </Button>
            <Button
              onClick={migrateForm.handleSubmit(onManualMigrate)}
              disabled={busy === "migrate"}
            >
              {busy === "migrate" ? "Migrating…" : "Migrate"}
            </Button>
          </>
        }
      >
        <form
          className="space-y-3"
          onSubmit={migrateForm.handleSubmit(onManualMigrate)}
        >
          <Field
            label="From option"
            error={migrateForm.formState.errors.from_option_id?.message}
          >
            <Select {...migrateForm.register("from_option_id")}>
              <option value="">— select —</option>
              {(enrollment?.options ?? []).map((o) => (
                <option key={o.option_id} value={o.option_id}>
                  {o.course_code}
                </option>
              ))}
            </Select>
          </Field>
          <Field
            label="To option"
            error={migrateForm.formState.errors.to_option_id?.message}
          >
            <Select {...migrateForm.register("to_option_id")}>
              <option value="">— select —</option>
              {(enrollment?.options ?? [])
                .filter((o) => !o.is_dissolved)
                .map((o) => (
                  <option key={o.option_id} value={o.option_id}>
                    {o.course_code}
                  </option>
                ))}
            </Select>
          </Field>
          <Field
            label="Student ID"
            error={migrateForm.formState.errors.student_id?.message}
          >
            <Select {...migrateForm.register("student_id")}>
              <option value="">— select —</option>
              {(enrollment?.options ?? [])
                .find(
                  (o) => o.option_id === migrateForm.watch("from_option_id"),
                )
                ?.students.map((s) => (
                  <option key={s.student_user_id} value={s.student_user_id}>
                    {s.usn ? `${s.usn} · ` : ""}
                    {s.name}
                  </option>
                ))}
            </Select>
          </Field>
          <Field
            label="Reason"
            error={migrateForm.formState.errors.reason?.message}
          >
            <Input {...migrateForm.register("reason")} />
          </Field>
          {actionErr ? <ErrorText>{actionErr}</ErrorText> : null}
        </form>
      </Dialog>
    </div>
  );
}
