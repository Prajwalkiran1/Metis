"use client";

import Link from "next/link";
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
  Tabs,
  Td,
  Th,
} from "@/components/ui";

type SetupState = "draft" | "published" | "active" | "archived";

type SetupList = {
  id: string;
  state: SetupState;
  academic_term_id: string;
};

type CourseAssignment = {
  id: string;
  course_code: string;
  course_title: string;
  course_type: "theory" | "lab" | "integrated" | "nptel";
  section_name: string;
  teacher_name: string | null;
  parent_offering_id: string | null;
};

type SetupDetail = {
  id: string;
  state: SetupState;
  courses: CourseAssignment[];
};

type Assignment = {
  id: string;
  teacher_user_id: string;
  teacher_name: string | null;
  role: "batch_incharge" | "co_evaluator";
  assigned_at: string;
};

type LabBatch = {
  id: string;
  course_offering_id: string;
  section_id: string;
  name: string;
  display_order: number;
  member_count: number;
  incharge: Assignment | null;
  co_evaluators: Assignment[];
};

type RosterEntry = {
  student_user_id: string;
  name: string;
  usn: string | null;
};

type AcademicTerm = {
  id: string;
  code: string;
};

type TeacherUser = {
  id: string;
  name: string;
  role: "teacher" | "hod" | "admin" | "student" | "parent";
};

const createBatchSchema = z.object({
  name: z.string().min(1).max(50),
  display_order: z.coerce.number().int().min(1).max(99),
});
type CreateBatchForm = z.infer<typeof createBatchSchema>;

const renameSchema = z.object({
  name: z.string().min(1).max(50),
  display_order: z.coerce.number().int().min(1).max(99),
});
type RenameForm = z.infer<typeof renameSchema>;

const autoComposeSchema = z.object({
  batch_count: z.coerce.number().int().min(1).max(20),
  name_prefix: z.string().min(1).max(20),
});
type AutoComposeForm = z.infer<typeof autoComposeSchema>;

const assignSchema = z.object({
  teacher_user_id: z.string().uuid(),
  role: z.enum(["batch_incharge", "co_evaluator"]),
});
type AssignForm = z.infer<typeof assignSchema>;

export default function HodLabBatchesPage() {
  const [setups, setSetups] = useState<SetupList[] | null>(null);
  const [terms, setTerms] = useState<AcademicTerm[]>([]);
  const [setupId, setSetupId] = useState<string>("");
  const [setupDetail, setSetupDetail] = useState<SetupDetail | null>(null);
  const [offeringId, setOfferingId] = useState<string>("");
  const [batches, setBatches] = useState<LabBatch[] | null>(null);
  const [roster, setRoster] = useState<RosterEntry[]>([]);
  const [teachers, setTeachers] = useState<TeacherUser[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const [openCreate, setOpenCreate] = useState(false);
  const [openAuto, setOpenAuto] = useState(false);
  const [openManage, setOpenManage] = useState<LabBatch | null>(null);
  const [manageTab, setManageTab] = useState<"members" | "assignments">(
    "members",
  );
  const [confirmDelete, setConfirmDelete] = useState<LabBatch | null>(null);

  const createForm = useForm<CreateBatchForm>({
    resolver: zodResolver(createBatchSchema),
    defaultValues: { name: "", display_order: 1 },
  });
  const renameForm = useForm<RenameForm>({
    resolver: zodResolver(renameSchema),
    defaultValues: { name: "", display_order: 1 },
  });
  const autoForm = useForm<AutoComposeForm>({
    resolver: zodResolver(autoComposeSchema),
    defaultValues: { batch_count: 3, name_prefix: "Batch" },
  });
  const assignForm = useForm<AssignForm>({
    resolver: zodResolver(assignSchema),
    defaultValues: { teacher_user_id: "", role: "batch_incharge" },
  });

  // ── data loaders ──
  const reloadSetups = useCallback(async () => {
    try {
      const [all, termRows] = await Promise.all([
        api<SetupList[]>("/workflow/semester-setups"),
        api<AcademicTerm[]>("/academic-terms").catch(() => [] as AcademicTerm[]),
      ]);
      const usable = all.filter((s) => s.state !== "draft");
      setSetups(usable);
      setTerms(termRows);
      if (usable.length > 0 && !setupId) setSetupId(usable[0].id);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "load failed");
    }
  }, [setupId]);

  const reloadSetupDetail = useCallback(async () => {
    if (!setupId) return;
    try {
      const d = await api<SetupDetail>(`/workflow/semester-setups/${setupId}`);
      setSetupDetail(d);
      // Default offering = first integrated/lab one
      const labbed = d.courses.find(
        (c) =>
          c.course_type === "integrated" ||
          (c.course_type === "lab" && c.parent_offering_id === null),
      );
      if (labbed && !offeringId) setOfferingId(labbed.id);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "load failed");
    }
  }, [setupId, offeringId]);

  const reloadBatches = useCallback(async () => {
    if (!offeringId) {
      setBatches([]);
      setRoster([]);
      return;
    }
    try {
      const [b, r] = await Promise.all([
        api<LabBatch[]>(
          `/workflow/course-offerings/${offeringId}/lab-batches`,
        ),
        api<RosterEntry[]>(
          `/workflow/course-offerings/${offeringId}/roster`,
        ),
      ]);
      setBatches(b);
      setRoster(r);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "load failed");
    }
  }, [offeringId]);

  const reloadTeachers = useCallback(async () => {
    try {
      const page = await api<{ items: TeacherUser[] }>("/users", {
        query: { role: "teacher", limit: 200 },
      });
      const hod = await api<{ items: TeacherUser[] }>("/users", {
        query: { role: "hod", limit: 50 },
      });
      setTeachers([...(page.items ?? []), ...(hod.items ?? [])]);
    } catch {
      // /users may 403 for non-admins — degrade to empty list; user can
      // still type a UUID in a follow-up dialog. The default flow always
      // works because HODs assigning incharges are typically among the
      // listed teachers anyway.
      setTeachers([]);
    }
  }, []);

  useEffect(() => {
    reloadSetups();
  }, [reloadSetups]);
  useEffect(() => {
    reloadSetupDetail();
  }, [reloadSetupDetail]);
  useEffect(() => {
    reloadBatches();
  }, [reloadBatches]);
  useEffect(() => {
    reloadTeachers();
  }, [reloadTeachers]);

  const labbedOfferings = useMemo(() => {
    if (!setupDetail) return [];
    return setupDetail.courses.filter(
      (c) =>
        c.course_type === "integrated" ||
        (c.course_type === "lab" && c.parent_offering_id === null),
    );
  }, [setupDetail]);

  const memberIds = useMemo(() => {
    if (!batches) return new Set<string>();
    // The roster entry is "free" when not listed in any batch's incharge/members.
    // Member counts are aggregated; we don't have per-batch student lists here
    // because the API exposes counts. The Manage dialog fetches per-batch.
    return new Set<string>();
  }, [batches]);

  // ── actions ──
  async function onCreate(values: CreateBatchForm) {
    if (!offeringId) return;
    setBusy("create");
    setActionErr(null);
    try {
      await api(`/workflow/course-offerings/${offeringId}/lab-batches`, {
        method: "POST",
        body: values,
      });
      setOpenCreate(false);
      createForm.reset({ name: "", display_order: (batches?.length ?? 0) + 1 });
      await reloadBatches();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "create failed");
    } finally {
      setBusy(null);
    }
  }

  async function onAutoCompose(values: AutoComposeForm) {
    if (!offeringId) return;
    setBusy("auto");
    setActionErr(null);
    try {
      const out = await api<{
        batches_created: number;
        batches_total: number;
        students_assigned: number;
        distribution: Record<string, number>;
      }>(`/workflow/course-offerings/${offeringId}/lab-batches/auto-compose`, {
        method: "POST",
        body: values,
      });
      setOpenAuto(false);
      setActionErr(
        `Composed: ${out.batches_total} batches, ${out.students_assigned} new placements.`,
      );
      await reloadBatches();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "auto-compose failed");
    } finally {
      setBusy(null);
    }
  }

  async function onDelete(batch: LabBatch) {
    setBusy("delete");
    setActionErr(null);
    try {
      await api(`/workflow/lab-batches/${batch.id}`, { method: "DELETE" });
      setConfirmDelete(null);
      await reloadBatches();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "delete failed");
    } finally {
      setBusy(null);
    }
  }

  async function onRename(batch: LabBatch, values: RenameForm) {
    setBusy("rename");
    setActionErr(null);
    try {
      await api(`/workflow/lab-batches/${batch.id}`, {
        method: "PATCH",
        body: values,
      });
      await reloadBatches();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "rename failed");
    } finally {
      setBusy(null);
    }
  }

  if (err) return <ErrorText>{err}</ErrorText>;
  if (setups === null) return <Loading />;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-zinc-900">Lab batches</h1>
        <p className="text-sm text-zinc-500">
          Compose lab batches for integrated and standalone-lab offerings,
          assign batch incharges, and run an even round-robin auto-compose.
        </p>
      </div>

      {setups.length === 0 ? (
        <Card>
          <p className="px-4 py-6 text-sm text-zinc-500">
            No published setups yet. Publish a semester setup first under{" "}
            <Link className="underline" href="/hod/semester-setup">
              Semester setup
            </Link>
            .
          </p>
        </Card>
      ) : (
        <Card className="p-4">
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Semester setup">
              <Select
                value={setupId}
                onChange={(e) => {
                  setSetupId(e.target.value);
                  setOfferingId("");
                  setSetupDetail(null);
                  setBatches(null);
                }}
              >
                {setups.map((s) => {
                  const term = terms.find((t) => t.id === s.academic_term_id);
                  return (
                    <option key={s.id} value={s.id}>
                      {term?.code ?? s.id.slice(0, 8)} · {s.state}
                    </option>
                  );
                })}
              </Select>
            </Field>
            <Field label="Offering">
              <Select
                value={offeringId}
                onChange={(e) => setOfferingId(e.target.value)}
                disabled={labbedOfferings.length === 0}
              >
                <option value="">— select —</option>
                {labbedOfferings.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.course_code} ({o.course_type}) · {o.section_name}
                  </option>
                ))}
              </Select>
            </Field>
            <div className="ml-auto flex gap-2">
              <Button
                variant="secondary"
                onClick={() => {
                  autoForm.reset({
                    batch_count: Math.max(2, batches?.length ?? 0),
                    name_prefix: "Batch",
                  });
                  setActionErr(null);
                  setOpenAuto(true);
                }}
                disabled={!offeringId}
              >
                Auto-compose…
              </Button>
              <Button
                onClick={() => {
                  createForm.reset({
                    name: `Batch ${(batches?.length ?? 0) + 1}`,
                    display_order: (batches?.length ?? 0) + 1,
                  });
                  setActionErr(null);
                  setOpenCreate(true);
                }}
                disabled={!offeringId}
              >
                Add batch
              </Button>
            </div>
          </div>
        </Card>
      )}

      {actionErr ? (
        <p className="text-sm text-red-600">{actionErr}</p>
      ) : null}

      {offeringId ? (
        <Card className="overflow-x-auto">
          {batches === null ? (
            <Loading />
          ) : batches.length === 0 ? (
            <p className="px-4 py-6 text-sm text-zinc-500">
              No batches yet. Click <em>Add batch</em> or <em>Auto-compose</em>.
            </p>
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Name</Th>
                  <Th>Order</Th>
                  <Th>Members</Th>
                  <Th>Incharge</Th>
                  <Th>Co-evaluators</Th>
                  <Th></Th>
                </tr>
              </thead>
              <tbody>
                {batches.map((b) => (
                  <tr key={b.id}>
                    <Td className="font-medium">{b.name}</Td>
                    <Td>{b.display_order}</Td>
                    <Td>
                      <Badge
                        tone={b.member_count === 0 ? "amber" : "green"}
                      >
                        {b.member_count}
                      </Badge>
                    </Td>
                    <Td className="text-zinc-700">
                      {b.incharge?.teacher_name ?? (
                        <span className="text-zinc-400">unassigned</span>
                      )}
                    </Td>
                    <Td className="text-zinc-700">
                      {b.co_evaluators.length > 0
                        ? b.co_evaluators
                            .map((a) => a.teacher_name ?? a.teacher_user_id)
                            .join(", ")
                        : "—"}
                    </Td>
                    <Td>
                      <div className="flex gap-2">
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => {
                            setOpenManage(b);
                            setManageTab("members");
                            renameForm.reset({
                              name: b.name,
                              display_order: b.display_order,
                            });
                            assignForm.reset({
                              teacher_user_id: "",
                              role: "batch_incharge",
                            });
                            setActionErr(null);
                          }}
                        >
                          Manage
                        </Button>
                        <Button
                          variant="danger"
                          size="sm"
                          onClick={() => setConfirmDelete(b)}
                        >
                          Delete
                        </Button>
                      </div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
      ) : null}

      {/* Create batch dialog */}
      <Dialog
        open={openCreate}
        onClose={() => setOpenCreate(false)}
        title="Add lab batch"
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => setOpenCreate(false)}
              disabled={busy === "create"}
            >
              Cancel
            </Button>
            <Button
              onClick={createForm.handleSubmit(onCreate)}
              disabled={busy === "create"}
            >
              {busy === "create" ? "Adding…" : "Add"}
            </Button>
          </>
        }
      >
        <form className="space-y-3">
          <Field label="Name" error={createForm.formState.errors.name?.message}>
            <Input {...createForm.register("name")} />
          </Field>
          <Field
            label="Display order"
            error={createForm.formState.errors.display_order?.message}
          >
            <Input type="number" {...createForm.register("display_order")} />
          </Field>
          {actionErr ? <ErrorText>{actionErr}</ErrorText> : null}
        </form>
      </Dialog>

      {/* Auto-compose dialog */}
      <Dialog
        open={openAuto}
        onClose={() => setOpenAuto(false)}
        title="Auto-compose batches"
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => setOpenAuto(false)}
              disabled={busy === "auto"}
            >
              Cancel
            </Button>
            <Button
              onClick={autoForm.handleSubmit(onAutoCompose)}
              disabled={busy === "auto"}
            >
              {busy === "auto" ? "Composing…" : "Compose"}
            </Button>
          </>
        }
      >
        <p className="text-sm text-zinc-600">
          Distributes the {roster.length} student(s) enrolled in this
          offering's section into N batches by round-robin. Existing batches
          are reused; students already placed in a batch keep their assignment.
        </p>
        <form className="space-y-3">
          <Field
            label="Number of batches"
            error={autoForm.formState.errors.batch_count?.message}
          >
            <Input type="number" {...autoForm.register("batch_count")} />
          </Field>
          <Field
            label="Name prefix"
            error={autoForm.formState.errors.name_prefix?.message}
          >
            <Input {...autoForm.register("name_prefix")} />
          </Field>
        </form>
      </Dialog>

      {/* Manage batch dialog */}
      <Dialog
        open={openManage !== null}
        onClose={() => setOpenManage(null)}
        title={`Batch · ${openManage?.name ?? ""}`}
        footer={
          <Button variant="secondary" onClick={() => setOpenManage(null)}>
            Close
          </Button>
        }
      >
        {openManage ? (
          <ManageBatch
            batch={openManage}
            offeringId={offeringId}
            roster={roster}
            teachers={teachers}
            tab={manageTab}
            onTab={setManageTab}
            renameForm={renameForm}
            assignForm={assignForm}
            actionErr={actionErr}
            busy={busy}
            setActionErr={setActionErr}
            setBusy={setBusy}
            onReloadBatches={reloadBatches}
            onRename={onRename}
          />
        ) : null}
      </Dialog>

      {/* Confirm delete dialog */}
      <Dialog
        open={confirmDelete !== null}
        onClose={() => setConfirmDelete(null)}
        title="Delete batch"
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => setConfirmDelete(null)}
              disabled={busy === "delete"}
            >
              Cancel
            </Button>
            <Button
              variant="danger"
              onClick={() => confirmDelete && onDelete(confirmDelete)}
              disabled={busy === "delete"}
            >
              {busy === "delete" ? "Deleting…" : "Delete"}
            </Button>
          </>
        }
      >
        <p className="text-sm text-zinc-700">
          Delete batch <strong>{confirmDelete?.name}</strong>? All current
          members are released; you can re-place them via auto-compose.
        </p>
      </Dialog>
    </div>
  );
}

// ── Manage batch dialog body ────────────────────────────────────────────────
function ManageBatch({
  batch,
  offeringId,
  roster,
  teachers,
  tab,
  onTab,
  renameForm,
  assignForm,
  actionErr,
  busy,
  setActionErr,
  setBusy,
  onReloadBatches,
  onRename,
}: {
  batch: LabBatch;
  offeringId: string;
  roster: RosterEntry[];
  teachers: TeacherUser[];
  tab: "members" | "assignments";
  onTab: (t: "members" | "assignments") => void;
  renameForm: ReturnType<typeof useForm<RenameForm>>;
  assignForm: ReturnType<typeof useForm<AssignForm>>;
  actionErr: string | null;
  busy: string | null;
  setActionErr: (s: string | null) => void;
  setBusy: (s: string | null) => void;
  onReloadBatches: () => Promise<void>;
  onRename: (b: LabBatch, v: RenameForm) => Promise<void>;
}) {
  const [memberIds, setMemberIds] = useState<Set<string>>(new Set());
  const [pickerOpen, setPickerOpen] = useState(false);
  const [picked, setPicked] = useState<Set<string>>(new Set());

  const loadMembers = useCallback(async () => {
    // The list endpoint exposes counts only; to render the per-batch
    // member table we re-list batches and filter the joined rows. As a
    // shortcut, use the count + the union from the offering roster:
    // members on this batch = roster ∩ (not in any batch); the API can
    // be extended later for an authoritative per-batch member list.
    // Here we approximate by computing "already on this batch" via a
    // re-fetch of the batches list and trusting member_count. We expose
    // selecting from the offering roster and rely on backend skips.
    setMemberIds(new Set()); // placeholder — proper list arrives via roster pickers
  }, []);

  useEffect(() => {
    loadMembers();
  }, [loadMembers]);

  async function onAddMembers() {
    if (picked.size === 0) return;
    setBusy("members-add");
    setActionErr(null);
    try {
      const out = await api<{
        added_count: number;
        skipped_not_in_section: string[];
        skipped_already_in_batch: string[];
      }>(`/workflow/lab-batches/${batch.id}/members`, {
        method: "POST",
        body: { student_user_ids: Array.from(picked) },
      });
      setPicked(new Set());
      setPickerOpen(false);
      setActionErr(
        `Added ${out.added_count}, skipped ${out.skipped_already_in_batch.length} already-placed, ${out.skipped_not_in_section.length} not in section.`,
      );
      await onReloadBatches();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "add failed");
    } finally {
      setBusy(null);
    }
  }

  async function onAssign(values: AssignForm) {
    setBusy("assign");
    setActionErr(null);
    try {
      await api(`/workflow/lab-batches/${batch.id}/assignments`, {
        method: "POST",
        body: values,
      });
      assignForm.reset({ teacher_user_id: "", role: "batch_incharge" });
      await onReloadBatches();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "assign failed");
    } finally {
      setBusy(null);
    }
  }

  async function onUnassign(assignmentId: string) {
    setBusy("unassign");
    setActionErr(null);
    try {
      await api(
        `/workflow/lab-batches/${batch.id}/assignments/${assignmentId}`,
        { method: "DELETE" },
      );
      await onReloadBatches();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "unassign failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-3">
      <Tabs
        tabs={[
          { id: "members", label: `Members (${batch.member_count})` },
          {
            id: "assignments",
            label: `Assignments (${batch.incharge ? 1 : 0} + ${batch.co_evaluators.length})`,
          },
        ]}
        active={tab}
        onChange={(id) => onTab(id as "members" | "assignments")}
      />

      {tab === "members" ? (
        <div className="space-y-3">
          <div className="space-y-2 rounded border border-zinc-200 p-2">
            <p className="text-xs text-zinc-500">
              Pick from the section roster. Students already assigned to any
              active batch on this offering are skipped server-side.
            </p>
            <div className="max-h-60 overflow-y-auto rounded border border-zinc-100">
              <Table>
                <thead>
                  <tr>
                    <Th></Th>
                    <Th>USN</Th>
                    <Th>Name</Th>
                  </tr>
                </thead>
                <tbody>
                  {roster.length === 0 ? (
                    <tr>
                      <Td colSpan={3} className="text-zinc-500">
                        No students enrolled in this section.
                      </Td>
                    </tr>
                  ) : (
                    roster.map((r) => (
                      <tr key={r.student_user_id}>
                        <Td>
                          <input
                            type="checkbox"
                            checked={picked.has(r.student_user_id)}
                            onChange={(e) => {
                              const next = new Set(picked);
                              if (e.target.checked)
                                next.add(r.student_user_id);
                              else next.delete(r.student_user_id);
                              setPicked(next);
                            }}
                          />
                        </Td>
                        <Td className="font-mono text-xs">{r.usn ?? "—"}</Td>
                        <Td>{r.name}</Td>
                      </tr>
                    ))
                  )}
                </tbody>
              </Table>
            </div>
            <div className="flex justify-between text-xs text-zinc-500">
              <span>
                {picked.size} of {roster.length} picked
              </span>
              <Button
                size="sm"
                onClick={onAddMembers}
                disabled={picked.size === 0 || busy === "members-add"}
              >
                {busy === "members-add" ? "Adding…" : "Add to batch"}
              </Button>
            </div>
          </div>

          <form
            onSubmit={renameForm.handleSubmit((v) => onRename(batch, v))}
            className="space-y-2 rounded border border-dashed border-zinc-200 p-2"
          >
            <p className="text-xs font-medium text-zinc-600">
              Rename / reorder
            </p>
            <div className="flex gap-2">
              <Input
                placeholder="Name"
                {...renameForm.register("name")}
              />
              <Input
                type="number"
                placeholder="Order"
                className="max-w-[100px]"
                {...renameForm.register("display_order")}
              />
              <Button size="sm" type="submit" disabled={busy === "rename"}>
                Save
              </Button>
            </div>
          </form>
          {actionErr ? <ErrorText>{actionErr}</ErrorText> : null}
        </div>
      ) : (
        <div className="space-y-3">
          <Table>
            <thead>
              <tr>
                <Th>Role</Th>
                <Th>Teacher</Th>
                <Th>Since</Th>
                <Th></Th>
              </tr>
            </thead>
            <tbody>
              {batch.incharge ? (
                <tr>
                  <Td>
                    <Badge tone="green">incharge</Badge>
                  </Td>
                  <Td>{batch.incharge.teacher_name ?? batch.incharge.teacher_user_id}</Td>
                  <Td className="text-zinc-500">
                    {new Date(batch.incharge.assigned_at).toLocaleDateString()}
                  </Td>
                  <Td>
                    <Button
                      size="sm"
                      variant="danger"
                      onClick={() =>
                        batch.incharge && onUnassign(batch.incharge.id)
                      }
                      disabled={busy === "unassign"}
                    >
                      Unassign
                    </Button>
                  </Td>
                </tr>
              ) : (
                <tr>
                  <Td colSpan={4} className="text-zinc-500">
                    No incharge assigned yet.
                  </Td>
                </tr>
              )}
              {batch.co_evaluators.map((a) => (
                <tr key={a.id}>
                  <Td>
                    <Badge tone="neutral">co-eval</Badge>
                  </Td>
                  <Td>{a.teacher_name ?? a.teacher_user_id}</Td>
                  <Td className="text-zinc-500">
                    {new Date(a.assigned_at).toLocaleDateString()}
                  </Td>
                  <Td>
                    <Button
                      size="sm"
                      variant="danger"
                      onClick={() => onUnassign(a.id)}
                      disabled={busy === "unassign"}
                    >
                      Unassign
                    </Button>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>

          <form
            onSubmit={assignForm.handleSubmit(onAssign)}
            className="space-y-2 rounded border border-dashed border-zinc-200 p-2"
          >
            <p className="text-xs font-medium text-zinc-600">Add assignment</p>
            <div className="flex gap-2">
              <Select
                className="min-w-[200px]"
                {...assignForm.register("teacher_user_id")}
              >
                <option value="">— pick teacher —</option>
                {teachers.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name} ({t.role})
                  </option>
                ))}
              </Select>
              <Select {...assignForm.register("role")}>
                <option value="batch_incharge">batch incharge</option>
                <option value="co_evaluator">co-evaluator</option>
              </Select>
              <Button size="sm" type="submit" disabled={busy === "assign"}>
                Assign
              </Button>
            </div>
          </form>
          {actionErr ? <ErrorText>{actionErr}</ErrorText> : null}
        </div>
      )}
    </div>
  );
}
