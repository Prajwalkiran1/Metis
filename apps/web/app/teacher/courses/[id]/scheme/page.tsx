"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useForm, useFieldArray, type UseFormReturn } from "react-hook-form";
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

type CourseType = "theory" | "lab" | "integrated" | "nptel";
type ComponentKind =
  | "cie"
  | "aat"
  | "lab"
  | "assignment"
  | "see"
  | "nptel_assignment"
  | "nptel_final";

type SchemeComponent = {
  id: string;
  kind: ComponentKind;
  label: string;
  max_marks: number;
  weight_percent: number;
  ordinal: number;
  is_dropped_in_best_of: boolean;
  metadata_json: Record<string, unknown>;
};

type Scheme = {
  id: string;
  course_offering_id: string;
  template_id: string | null;
  template_name: string | null;
  is_locked: boolean;
  locked_at: string | null;
  locked_reason: string | null;
  components: SchemeComponent[];
  aat_total_percent: number;
  weight_total_percent: number;
  inherited_from_offering_id: string | null;
};

type Template = {
  id: string;
  name: string;
  applies_to_course_type: CourseType;
  is_institutional: boolean;
  default_components: {
    kind: ComponentKind;
    label: string;
    max_marks: number;
    weight_percent: number;
    ordinal: number;
  }[];
};

type CourseAssignment = {
  id: string;
  course_code: string;
  course_title: string;
  course_type: CourseType;
  section_name: string;
};

type SetupList = { id: string; state: string };
type SetupDetail = { id: string; courses: CourseAssignment[] };

const componentSchema = z.object({
  kind: z.enum([
    "cie",
    "aat",
    "lab",
    "assignment",
    "see",
    "nptel_assignment",
    "nptel_final",
  ]),
  label: z.string().min(1).max(50),
  max_marks: z.coerce.number().min(0).max(1000),
  weight_percent: z.coerce.number().min(0).max(100),
  ordinal: z.coerce.number().int().min(1).max(20),
  is_dropped_in_best_of: z.boolean().optional(),
});

const replaceCustomSchema = z.object({
  mode: z.enum(["custom"]),
  components: z.array(componentSchema).min(1).max(20),
});
const replaceTemplateSchema = z.object({
  mode: z.enum(["template"]),
  template_id: z.string().uuid(),
});
const replaceCloneSchema = z.object({
  mode: z.enum(["clone"]),
  clone_from_offering_id: z.string().uuid(),
});

const patchSchema = z.object({
  label: z.string().min(1).max(50),
  max_marks: z.coerce.number().min(0).max(1000),
  weight_percent: z.coerce.number().min(0).max(100),
  ordinal: z.coerce.number().int().min(1).max(20),
  is_dropped_in_best_of: z.boolean().optional(),
});
type PatchForm = z.infer<typeof patchSchema>;

const lockSchema = z.object({
  reason: z.string().max(500).optional().or(z.literal("")),
});
type LockForm = z.infer<typeof lockSchema>;

const unlockSchema = z.object({
  reason: z.string().min(1).max(2000),
});
type UnlockForm = z.infer<typeof unlockSchema>;

const customSchema = z.object({
  components: z.array(componentSchema).min(1).max(20),
});
type CustomForm = z.infer<typeof customSchema>;

function aatTotal(
  components: { kind: ComponentKind; weight_percent: number }[],
): number {
  return components
    .filter((c) => c.kind === "aat")
    .reduce((s, c) => s + Number(c.weight_percent || 0), 0);
}
function weightTotal(
  components: { weight_percent: number }[],
): number {
  return components.reduce(
    (s, c) => s + Number(c.weight_percent || 0),
    0,
  );
}

export default function TeacherCourseSchemePage() {
  const params = useParams<{ id: string }>();
  const offeringId = params?.id ?? "";
  const [scheme, setScheme] = useState<Scheme | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [siblings, setSiblings] = useState<CourseAssignment[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [openTemplate, setOpenTemplate] = useState(false);
  const [openClone, setOpenClone] = useState(false);
  const [openCustom, setOpenCustom] = useState(false);
  const [openPatch, setOpenPatch] = useState<SchemeComponent | null>(null);
  const [openLock, setOpenLock] = useState(false);
  const [openUnlock, setOpenUnlock] = useState(false);

  const templateForm = useForm<{ template_id: string }>({
    defaultValues: { template_id: "" },
  });
  const cloneForm = useForm<{ clone_from_offering_id: string }>({
    defaultValues: { clone_from_offering_id: "" },
  });
  const customForm = useForm<CustomForm>({
    resolver: zodResolver(customSchema),
    defaultValues: {
      components: [
        {
          kind: "cie",
          label: "CIE-1",
          max_marks: 40,
          weight_percent: 25,
          ordinal: 1,
        },
      ],
    },
  });
  const customArray = useFieldArray({
    control: customForm.control,
    name: "components",
  });
  const patchForm = useForm<PatchForm>({
    resolver: zodResolver(patchSchema),
    defaultValues: {
      label: "",
      max_marks: 0,
      weight_percent: 0,
      ordinal: 1,
    },
  });
  const lockForm = useForm<LockForm>({
    resolver: zodResolver(lockSchema),
    defaultValues: { reason: "" },
  });
  const unlockForm = useForm<UnlockForm>({
    resolver: zodResolver(unlockSchema),
    defaultValues: { reason: "" },
  });

  const reload = useCallback(async () => {
    if (!offeringId) return;
    try {
      const s = await api<Scheme>(
        `/workflow/course-offerings/${offeringId}/scheme`,
      );
      setScheme(s);
    } catch (e) {
      if (e instanceof ApiError && e.code === "no_scheme") {
        setScheme(null);
      } else {
        setErr(e instanceof ApiError ? e.message : "load failed");
      }
    }
  }, [offeringId]);

  const reloadTemplates = useCallback(async () => {
    try {
      const rows = await api<Template[]>("/workflow/scheme-templates");
      setTemplates(rows);
    } catch {
      setTemplates([]);
    }
  }, []);

  const reloadSiblings = useCallback(async () => {
    // For the clone-from picker: list the offerings under the same setup as
    // this one. We don't have a dedicated endpoint, so walk the setups list.
    try {
      const setups = await api<SetupList[]>("/workflow/semester-setups");
      const usable = setups.filter((s) => s.state !== "draft");
      const allOfferings: CourseAssignment[] = [];
      for (const s of usable) {
        const detail = await api<SetupDetail>(
          `/workflow/semester-setups/${s.id}`,
        );
        allOfferings.push(...detail.courses);
      }
      setSiblings(allOfferings.filter((o) => o.id !== offeringId));
    } catch {
      setSiblings([]);
    }
  }, [offeringId]);

  useEffect(() => {
    reload();
    reloadTemplates();
    reloadSiblings();
  }, [reload, reloadTemplates, reloadSiblings]);

  const inherited = scheme?.inherited_from_offering_id ?? null;
  const isLocked = !!scheme?.is_locked;

  async function onPickTemplate(values: { template_id: string }) {
    if (!values.template_id) {
      setActionErr("pick a template");
      return;
    }
    setBusy("template");
    setActionErr(null);
    try {
      await api(`/workflow/course-offerings/${offeringId}/scheme`, {
        method: "POST",
        body: { template_id: values.template_id },
      });
      setOpenTemplate(false);
      await reload();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "save failed");
    } finally {
      setBusy(null);
    }
  }

  async function onPickClone(values: { clone_from_offering_id: string }) {
    if (!values.clone_from_offering_id) {
      setActionErr("pick a source offering");
      return;
    }
    setBusy("clone");
    setActionErr(null);
    try {
      await api(`/workflow/course-offerings/${offeringId}/scheme`, {
        method: "POST",
        body: { clone_from_offering_id: values.clone_from_offering_id },
      });
      setOpenClone(false);
      await reload();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "save failed");
    } finally {
      setBusy(null);
    }
  }

  async function onPickCustom(values: CustomForm) {
    setBusy("custom");
    setActionErr(null);
    try {
      await api(`/workflow/course-offerings/${offeringId}/scheme`, {
        method: "POST",
        body: { components: values.components },
      });
      setOpenCustom(false);
      await reload();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "save failed");
    } finally {
      setBusy(null);
    }
  }

  async function onPatchComponent(values: PatchForm) {
    if (!openPatch) return;
    setBusy("patch");
    setActionErr(null);
    try {
      await api(
        `/workflow/course-offerings/${offeringId}/scheme/components/${openPatch.id}`,
        { method: "PATCH", body: values },
      );
      setOpenPatch(null);
      await reload();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "patch failed");
    } finally {
      setBusy(null);
    }
  }

  async function onLock(values: LockForm) {
    setBusy("lock");
    setActionErr(null);
    try {
      await api(`/workflow/course-offerings/${offeringId}/scheme/lock`, {
        method: "POST",
        body: { reason: values.reason || null },
      });
      setOpenLock(false);
      await reload();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "lock failed");
    } finally {
      setBusy(null);
    }
  }

  async function onUnlock(values: UnlockForm) {
    setBusy("unlock");
    setActionErr(null);
    try {
      await api(`/workflow/course-offerings/${offeringId}/scheme/unlock`, {
        method: "POST",
        body: values,
      });
      setOpenUnlock(false);
      await reload();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "unlock failed");
    } finally {
      setBusy(null);
    }
  }

  if (err) return <ErrorText>{err}</ErrorText>;

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold text-zinc-900">
            Assessment scheme
          </h1>
          <p className="text-sm text-zinc-500">
            Configure components, weights, and the AAT cap. Lock when ready
            for marks entry — HOD unlocks if changes become necessary later.
          </p>
        </div>
        <Link
          href="/teacher/attendance"
          className="text-sm text-zinc-500 underline"
        >
          ← Back
        </Link>
      </div>

      {inherited ? (
        <Card className="border-amber-300 bg-amber-50 p-4 text-sm text-amber-800">
          <p className="font-medium">Inherited from parent</p>
          <p className="mt-1">
            This offering is the lab side of an integrated course. The scheme
            lives on the theory parent. Edit there:{" "}
            <Link
              href={`/teacher/courses/${inherited}/scheme`}
              className="underline"
            >
              go to parent
            </Link>
            .
          </p>
        </Card>
      ) : null}

      {scheme ? (
        <Card className="p-4">
          <div className="flex flex-wrap items-center gap-4">
            <Badge
              tone={
                scheme.aat_total_percent > 40
                  ? "red"
                  : scheme.aat_total_percent > 20
                    ? "amber"
                    : "green"
              }
            >
              AAT {scheme.aat_total_percent.toFixed(1)}%
            </Badge>
            <Badge
              tone={
                Math.abs(scheme.weight_total_percent - 100) < 0.01
                  ? "green"
                  : "amber"
              }
            >
              weight {scheme.weight_total_percent.toFixed(1)}%
            </Badge>
            <Badge tone={scheme.is_locked ? "red" : "neutral"}>
              {scheme.is_locked ? "locked" : "open"}
            </Badge>
            {scheme.template_name ? (
              <Badge tone="neutral">template · {scheme.template_name}</Badge>
            ) : null}
            <div className="ml-auto flex gap-2">
              {scheme.is_locked ? (
                <Button onClick={() => setOpenUnlock(true)}>Unlock (HOD)</Button>
              ) : (
                <>
                  <Button
                    variant="secondary"
                    onClick={() => {
                      setActionErr(null);
                      templateForm.reset({ template_id: "" });
                      setOpenTemplate(true);
                    }}
                    disabled={inherited !== null}
                  >
                    Replace from template
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={() => {
                      setActionErr(null);
                      cloneForm.reset({ clone_from_offering_id: "" });
                      setOpenClone(true);
                    }}
                    disabled={inherited !== null}
                  >
                    Clone from offering
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={() => {
                      setActionErr(null);
                      customForm.reset({
                        components: scheme.components.map((c) => ({
                          kind: c.kind,
                          label: c.label,
                          max_marks: c.max_marks,
                          weight_percent: c.weight_percent,
                          ordinal: c.ordinal,
                          is_dropped_in_best_of: c.is_dropped_in_best_of,
                        })),
                      });
                      setOpenCustom(true);
                    }}
                    disabled={inherited !== null}
                  >
                    Edit custom
                  </Button>
                  <Button
                    onClick={() => {
                      lockForm.reset({ reason: "" });
                      setActionErr(null);
                      setOpenLock(true);
                    }}
                    disabled={inherited !== null}
                  >
                    Lock
                  </Button>
                </>
              )}
            </div>
          </div>
          {scheme.locked_reason ? (
            <p className="mt-2 text-xs text-zinc-500">
              Locked reason: {scheme.locked_reason}
            </p>
          ) : null}
        </Card>
      ) : (
        <Card className="p-4 text-sm text-zinc-600">
          <p>No scheme yet. Pick a template or clone from another offering.</p>
          <div className="mt-3 flex gap-2">
            <Button onClick={() => setOpenTemplate(true)}>
              Replace from template
            </Button>
            <Button variant="secondary" onClick={() => setOpenClone(true)}>
              Clone from offering
            </Button>
          </div>
        </Card>
      )}

      {actionErr ? (
        <p className="text-sm text-red-600">{actionErr}</p>
      ) : null}

      {scheme ? (
        <Card className="overflow-x-auto">
          <Table>
            <thead>
              <tr>
                <Th>#</Th>
                <Th>Kind</Th>
                <Th>Label</Th>
                <Th>Max</Th>
                <Th>Weight %</Th>
                <Th>Best-of drop</Th>
                <Th></Th>
              </tr>
            </thead>
            <tbody>
              {scheme.components.map((c) => (
                <tr key={c.id}>
                  <Td>{c.ordinal}</Td>
                  <Td>
                    <Badge tone={c.kind === "aat" ? "amber" : "neutral"}>
                      {c.kind}
                    </Badge>
                  </Td>
                  <Td className="font-medium">{c.label}</Td>
                  <Td>{c.max_marks}</Td>
                  <Td>{c.weight_percent}</Td>
                  <Td>{c.is_dropped_in_best_of ? "yes" : "no"}</Td>
                  <Td>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => {
                        setActionErr(null);
                        patchForm.reset({
                          label: c.label,
                          max_marks: c.max_marks,
                          weight_percent: c.weight_percent,
                          ordinal: c.ordinal,
                          is_dropped_in_best_of: c.is_dropped_in_best_of,
                        });
                        setOpenPatch(c);
                      }}
                      disabled={isLocked || inherited !== null}
                    >
                      Edit
                    </Button>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      ) : null}

      {/* Replace from template */}
      <Dialog
        open={openTemplate}
        onClose={() => setOpenTemplate(false)}
        title="Replace scheme from template"
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => setOpenTemplate(false)}
              disabled={busy === "template"}
            >
              Cancel
            </Button>
            <Button
              onClick={templateForm.handleSubmit(onPickTemplate)}
              disabled={busy === "template"}
            >
              {busy === "template" ? "Applying…" : "Apply"}
            </Button>
          </>
        }
      >
        <form className="space-y-3">
          <Field label="Template">
            <Select {...templateForm.register("template_id")}>
              <option value="">— pick —</option>
              {templates.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.is_institutional ? "[I] " : ""}
                  {t.name} · {t.applies_to_course_type}
                </option>
              ))}
            </Select>
          </Field>
          <p className="text-xs text-zinc-500">
            Old components are soft-deleted and new ones inserted, so prior
            marks remain queryable.
          </p>
          {actionErr ? <ErrorText>{actionErr}</ErrorText> : null}
        </form>
      </Dialog>

      {/* Clone from sibling */}
      <Dialog
        open={openClone}
        onClose={() => setOpenClone(false)}
        title="Clone scheme from another offering"
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => setOpenClone(false)}
              disabled={busy === "clone"}
            >
              Cancel
            </Button>
            <Button
              onClick={cloneForm.handleSubmit(onPickClone)}
              disabled={busy === "clone"}
            >
              {busy === "clone" ? "Cloning…" : "Clone"}
            </Button>
          </>
        }
      >
        <form className="space-y-3">
          <Field label="Source offering">
            <Select {...cloneForm.register("clone_from_offering_id")}>
              <option value="">— pick —</option>
              {siblings.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.course_code} ({o.course_type}) · {o.section_name}
                </option>
              ))}
            </Select>
          </Field>
          {actionErr ? <ErrorText>{actionErr}</ErrorText> : null}
        </form>
      </Dialog>

      {/* Custom editor */}
      <Dialog
        open={openCustom}
        onClose={() => setOpenCustom(false)}
        title="Edit components"
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => setOpenCustom(false)}
              disabled={busy === "custom"}
            >
              Cancel
            </Button>
            <Button
              onClick={customForm.handleSubmit(onPickCustom)}
              disabled={busy === "custom"}
            >
              {busy === "custom" ? "Applying…" : "Replace"}
            </Button>
          </>
        }
      >
        <CustomEditor
          form={customForm}
          array={customArray}
          actionErr={actionErr}
        />
      </Dialog>

      {/* Component PATCH */}
      <Dialog
        open={openPatch !== null}
        onClose={() => setOpenPatch(null)}
        title={`Edit · ${openPatch?.label ?? ""}`}
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => setOpenPatch(null)}
              disabled={busy === "patch"}
            >
              Cancel
            </Button>
            <Button
              onClick={patchForm.handleSubmit(onPatchComponent)}
              disabled={busy === "patch"}
            >
              {busy === "patch" ? "Saving…" : "Save"}
            </Button>
          </>
        }
      >
        <form className="space-y-3">
          <Field label="Label" error={patchForm.formState.errors.label?.message}>
            <Input {...patchForm.register("label")} />
          </Field>
          <Field
            label="Max marks"
            error={patchForm.formState.errors.max_marks?.message}
          >
            <Input
              type="number"
              step="0.5"
              {...patchForm.register("max_marks")}
            />
          </Field>
          <Field
            label="Weight %"
            error={patchForm.formState.errors.weight_percent?.message}
          >
            <Input
              type="number"
              step="0.5"
              {...patchForm.register("weight_percent")}
            />
          </Field>
          <Field
            label="Ordinal"
            error={patchForm.formState.errors.ordinal?.message}
          >
            <Input type="number" {...patchForm.register("ordinal")} />
          </Field>
          <label className="flex items-center gap-2 text-xs text-zinc-700">
            <input
              type="checkbox"
              {...patchForm.register("is_dropped_in_best_of")}
            />
            drop the worst in best-of grouping
          </label>
          {openPatch?.kind === "aat" ? (
            <p className="text-xs text-amber-700">
              AAT total &gt; 20% requires HOD authorisation; &gt; 40% is
              rejected.
            </p>
          ) : null}
          {actionErr ? <ErrorText>{actionErr}</ErrorText> : null}
        </form>
      </Dialog>

      {/* Lock dialog */}
      <Dialog
        open={openLock}
        onClose={() => setOpenLock(false)}
        title="Lock scheme"
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => setOpenLock(false)}
              disabled={busy === "lock"}
            >
              Cancel
            </Button>
            <Button
              onClick={lockForm.handleSubmit(onLock)}
              disabled={busy === "lock"}
            >
              {busy === "lock" ? "Locking…" : "Lock"}
            </Button>
          </>
        }
      >
        <p className="text-sm text-zinc-700">
          Locking freezes the scheme so marks entry can begin. HOD must
          unlock before further component edits.
        </p>
        <Field label="Reason (optional)">
          <Input {...lockForm.register("reason")} />
        </Field>
        {actionErr ? <ErrorText>{actionErr}</ErrorText> : null}
      </Dialog>

      {/* Unlock dialog */}
      <Dialog
        open={openUnlock}
        onClose={() => setOpenUnlock(false)}
        title="Unlock scheme"
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => setOpenUnlock(false)}
              disabled={busy === "unlock"}
            >
              Cancel
            </Button>
            <Button
              onClick={unlockForm.handleSubmit(onUnlock)}
              disabled={busy === "unlock"}
            >
              {busy === "unlock" ? "Unlocking…" : "Unlock"}
            </Button>
          </>
        }
      >
        <p className="text-sm text-zinc-700">
          Unlock writes a typed override row to academic_overrides.
        </p>
        <Field
          label="Reason"
          error={unlockForm.formState.errors.reason?.message}
        >
          <Input {...unlockForm.register("reason")} />
        </Field>
        {actionErr ? <ErrorText>{actionErr}</ErrorText> : null}
      </Dialog>
    </div>
  );
}

function CustomEditor({
  form,
  array,
  actionErr,
}: {
  form: UseFormReturn<CustomForm>;
  array: ReturnType<typeof useFieldArray<CustomForm, "components">>;
  actionErr: string | null;
}) {
  const live = form.watch("components");
  const aat = aatTotal(
    (live ?? []) as { kind: ComponentKind; weight_percent: number }[],
  );
  const total = weightTotal(
    (live ?? []) as { weight_percent: number }[],
  );
  return (
    <form className="space-y-3" autoComplete="off">
      <div className="flex gap-2">
        <Badge tone={aat > 40 ? "red" : aat > 20 ? "amber" : "green"}>
          AAT {aat.toFixed(1)}%
        </Badge>
        <Badge tone={Math.abs(total - 100) < 0.01 ? "green" : "amber"}>
          weight {total.toFixed(1)}%
        </Badge>
      </div>
      <div className="max-h-72 space-y-2 overflow-y-auto">
        {array.fields.map((field, idx) => (
          <div
            key={field.id}
            className="grid grid-cols-12 items-end gap-2 rounded bg-zinc-50 p-2"
          >
            <div className="col-span-3">
              <Select {...form.register(`components.${idx}.kind` as const)}>
                <option value="cie">cie</option>
                <option value="aat">aat</option>
                <option value="lab">lab</option>
                <option value="assignment">assignment</option>
                <option value="see">see</option>
                <option value="nptel_assignment">nptel_assignment</option>
                <option value="nptel_final">nptel_final</option>
              </Select>
            </div>
            <div className="col-span-3">
              <Input
                placeholder="Label"
                {...form.register(`components.${idx}.label` as const)}
              />
            </div>
            <div className="col-span-2">
              <Input
                type="number"
                step="0.5"
                placeholder="Max"
                {...form.register(`components.${idx}.max_marks` as const)}
              />
            </div>
            <div className="col-span-2">
              <Input
                type="number"
                step="0.5"
                placeholder="Weight %"
                {...form.register(`components.${idx}.weight_percent` as const)}
              />
            </div>
            <div className="col-span-1">
              <Input
                type="number"
                placeholder="#"
                {...form.register(`components.${idx}.ordinal` as const)}
              />
            </div>
            <div className="col-span-1 flex justify-end">
              <Button
                size="sm"
                variant="ghost"
                type="button"
                onClick={() => array.remove(idx)}
              >
                ×
              </Button>
            </div>
          </div>
        ))}
      </div>
      <Button
        size="sm"
        variant="secondary"
        type="button"
        onClick={() =>
          array.append({
            kind: "cie",
            label: "",
            max_marks: 40,
            weight_percent: 0,
            ordinal: array.fields.length + 1,
          })
        }
      >
        + Add component
      </Button>
      {actionErr ? <ErrorText>{actionErr}</ErrorText> : null}
    </form>
  );
}
