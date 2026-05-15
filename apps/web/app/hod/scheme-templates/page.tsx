"use client";

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

type TemplateComponent = {
  kind: ComponentKind;
  label: string;
  max_marks: number;
  weight_percent: number;
  ordinal: number;
  metadata?: Record<string, unknown>;
};

type Template = {
  id: string;
  owner_department_id: string | null;
  owner_department_code: string | null;
  name: string;
  description: string | null;
  applies_to_course_type: CourseType;
  validation_rules: Record<string, unknown>;
  default_components: TemplateComponent[];
  is_active: boolean;
  is_institutional: boolean;
  usage_count: number;
};

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
  metadata: z.record(z.unknown()).optional(),
});

const templateFormSchema = z.object({
  name: z.string().min(1).max(100),
  description: z.string().max(2000).optional().or(z.literal("")),
  applies_to_course_type: z.enum(["theory", "lab", "integrated", "nptel"]),
  validation_rules_json: z.string().refine(
    (s) => {
      if (!s.trim()) return true;
      try {
        const parsed = JSON.parse(s);
        return parsed !== null && typeof parsed === "object";
      } catch {
        return false;
      }
    },
    { message: "validation_rules must be a JSON object" },
  ),
  default_components: z
    .array(componentSchema)
    .min(1, "at least one component")
    .max(20),
  is_active: z.boolean().optional(),
});
type TemplateForm = z.infer<typeof templateFormSchema>;

function aatTotal(components: TemplateComponent[]): number {
  return components
    .filter((c) => c.kind === "aat")
    .reduce((s, c) => s + Number(c.weight_percent || 0), 0);
}

function weightTotal(components: TemplateComponent[]): number {
  return components.reduce(
    (s, c) => s + Number(c.weight_percent || 0),
    0,
  );
}

export default function HodSchemeTemplatesPage() {
  const [templates, setTemplates] = useState<Template[] | null>(null);
  const [typeFilter, setTypeFilter] = useState<CourseType | "">("");
  const [err, setErr] = useState<string | null>(null);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [openTpl, setOpenTpl] = useState<Template | null>(null);
  const [openNew, setOpenNew] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<Template | null>(null);
  const [seedFrom, setSeedFrom] = useState<Template | null>(null);

  const form = useForm<TemplateForm>({
    resolver: zodResolver(templateFormSchema),
    defaultValues: {
      name: "",
      description: "",
      applies_to_course_type: "theory",
      validation_rules_json: "{}",
      default_components: [
        {
          kind: "cie",
          label: "CIE-1",
          max_marks: 40,
          weight_percent: 30,
          ordinal: 1,
        },
      ],
      is_active: true,
    },
  });
  const componentsArray = useFieldArray({
    control: form.control,
    name: "default_components",
  });

  const reload = useCallback(async () => {
    try {
      const rows = await api<Template[]>("/workflow/scheme-templates", {
        query: { applies_to_course_type: typeFilter || undefined },
      });
      setTemplates(rows);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "load failed");
    }
  }, [typeFilter]);

  useEffect(() => {
    reload();
  }, [reload]);

  // Recompute AAT total live so the band hint updates as the HOD types.
  const liveComponents = form.watch("default_components");
  const liveAat = aatTotal((liveComponents ?? []) as TemplateComponent[]);
  const liveTotal = weightTotal((liveComponents ?? []) as TemplateComponent[]);

  function openNewBlank() {
    setOpenNew(true);
    setSeedFrom(null);
    setActionErr(null);
    form.reset({
      name: "",
      description: "",
      applies_to_course_type: "theory",
      validation_rules_json: "{}",
      default_components: [
        {
          kind: "cie",
          label: "CIE-1",
          max_marks: 40,
          weight_percent: 30,
          ordinal: 1,
        },
      ],
      is_active: true,
    });
  }

  function openSeeded(seed: Template) {
    setOpenNew(true);
    setSeedFrom(seed);
    setActionErr(null);
    form.reset({
      name: `${seed.name} (copy)`,
      description: seed.description ?? "",
      applies_to_course_type: seed.applies_to_course_type,
      validation_rules_json: JSON.stringify(seed.validation_rules ?? {}, null, 2),
      default_components: seed.default_components.map((c) => ({
        kind: c.kind,
        label: c.label,
        max_marks: c.max_marks,
        weight_percent: c.weight_percent,
        ordinal: c.ordinal,
        metadata: c.metadata ?? {},
      })),
      is_active: true,
    });
  }

  async function onCreate(values: TemplateForm) {
    setBusy("save");
    setActionErr(null);
    try {
      const validation = values.validation_rules_json.trim()
        ? JSON.parse(values.validation_rules_json)
        : {};
      await api("/workflow/scheme-templates", {
        method: "POST",
        body: {
          name: values.name,
          description: values.description || undefined,
          applies_to_course_type: values.applies_to_course_type,
          validation_rules: validation,
          default_components: values.default_components,
        },
      });
      setOpenNew(false);
      await reload();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "save failed");
    } finally {
      setBusy(null);
    }
  }

  async function onPatch(tpl: Template, values: TemplateForm) {
    setBusy("save");
    setActionErr(null);
    try {
      const validation = values.validation_rules_json.trim()
        ? JSON.parse(values.validation_rules_json)
        : {};
      await api(`/workflow/scheme-templates/${tpl.id}`, {
        method: "PATCH",
        body: {
          name: values.name,
          description: values.description || undefined,
          validation_rules: validation,
          default_components: values.default_components,
          is_active: values.is_active,
        },
      });
      setOpenTpl(null);
      await reload();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "save failed");
    } finally {
      setBusy(null);
    }
  }

  async function onDelete(tpl: Template) {
    setBusy("delete");
    setActionErr(null);
    try {
      await api(`/workflow/scheme-templates/${tpl.id}`, { method: "DELETE" });
      setConfirmDelete(null);
      await reload();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "delete failed");
    } finally {
      setBusy(null);
    }
  }

  if (err) return <ErrorText>{err}</ErrorText>;
  if (templates === null) return <Loading />;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-zinc-900">
            Scheme templates
          </h1>
          <p className="text-sm text-zinc-500">
            Institutional templates are read-only; create or edit your
            department's templates here. Teachers pick from this list when
            configuring a course offering's scheme.
          </p>
        </div>
        <div className="flex gap-2">
          <Field label="Filter">
            <Select
              value={typeFilter}
              onChange={(e) =>
                setTypeFilter(e.target.value as CourseType | "")
              }
            >
              <option value="">All types</option>
              <option value="theory">theory</option>
              <option value="lab">lab</option>
              <option value="integrated">integrated</option>
              <option value="nptel">nptel</option>
            </Select>
          </Field>
          <div className="self-end">
            <Button onClick={openNewBlank}>New template</Button>
          </div>
        </div>
      </div>

      <Card className="overflow-x-auto">
        {templates.length === 0 ? (
          <p className="px-4 py-6 text-sm text-zinc-500">
            No templates match this filter.
          </p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Name</Th>
                <Th>Type</Th>
                <Th>Owner</Th>
                <Th>Components</Th>
                <Th>AAT %</Th>
                <Th>In use</Th>
                <Th>Active</Th>
                <Th></Th>
              </tr>
            </thead>
            <tbody>
              {templates.map((t) => (
                <tr key={t.id}>
                  <Td className="font-medium">{t.name}</Td>
                  <Td>
                    <Badge tone="neutral">{t.applies_to_course_type}</Badge>
                  </Td>
                  <Td>
                    {t.is_institutional ? (
                      <Badge tone="amber">institutional</Badge>
                    ) : (
                      <span className="text-zinc-700">
                        {t.owner_department_code ?? "dept"}
                      </span>
                    )}
                  </Td>
                  <Td>{t.default_components.length}</Td>
                  <Td>{aatTotal(t.default_components).toFixed(1)}</Td>
                  <Td>{t.usage_count}</Td>
                  <Td>
                    {t.is_active ? (
                      <Badge tone="green">active</Badge>
                    ) : (
                      <Badge tone="neutral">inactive</Badge>
                    )}
                  </Td>
                  <Td>
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => {
                          form.reset({
                            name: t.name,
                            description: t.description ?? "",
                            applies_to_course_type: t.applies_to_course_type,
                            validation_rules_json: JSON.stringify(
                              t.validation_rules ?? {},
                              null,
                              2,
                            ),
                            default_components: t.default_components.map(
                              (c) => ({
                                kind: c.kind,
                                label: c.label,
                                max_marks: c.max_marks,
                                weight_percent: c.weight_percent,
                                ordinal: c.ordinal,
                                metadata: c.metadata ?? {},
                              }),
                            ),
                            is_active: t.is_active,
                          });
                          setOpenTpl(t);
                          setActionErr(null);
                        }}
                      >
                        {t.is_institutional ? "View" : "Edit"}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => openSeeded(t)}
                      >
                        Use as base
                      </Button>
                      {t.is_institutional ? null : (
                        <Button
                          size="sm"
                          variant="danger"
                          onClick={() => setConfirmDelete(t)}
                        >
                          Delete
                        </Button>
                      )}
                    </div>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      {/* Edit-or-view dialog */}
      <Dialog
        open={openTpl !== null}
        onClose={() => setOpenTpl(null)}
        title={
          openTpl?.is_institutional
            ? `View · ${openTpl?.name}`
            : `Edit · ${openTpl?.name}`
        }
        footer={
          openTpl?.is_institutional ? (
            <Button variant="secondary" onClick={() => setOpenTpl(null)}>
              Close
            </Button>
          ) : (
            <>
              <Button
                variant="secondary"
                onClick={() => setOpenTpl(null)}
                disabled={busy === "save"}
              >
                Cancel
              </Button>
              <Button
                onClick={form.handleSubmit((v) => openTpl && onPatch(openTpl, v))}
                disabled={busy === "save"}
              >
                {busy === "save" ? "Saving…" : "Save"}
              </Button>
            </>
          )
        }
      >
        {openTpl ? (
          <TemplateFormBody
            form={form}
            componentsArray={componentsArray}
            readOnly={openTpl.is_institutional}
            aat={liveAat}
            weight={liveTotal}
            actionErr={actionErr}
          />
        ) : null}
      </Dialog>

      {/* New dialog */}
      <Dialog
        open={openNew}
        onClose={() => setOpenNew(false)}
        title={
          seedFrom ? `New (based on ${seedFrom.name})` : "New scheme template"
        }
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => setOpenNew(false)}
              disabled={busy === "save"}
            >
              Cancel
            </Button>
            <Button
              onClick={form.handleSubmit(onCreate)}
              disabled={busy === "save"}
            >
              {busy === "save" ? "Creating…" : "Create"}
            </Button>
          </>
        }
      >
        <TemplateFormBody
          form={form}
          componentsArray={componentsArray}
          readOnly={false}
          aat={liveAat}
          weight={liveTotal}
          actionErr={actionErr}
        />
      </Dialog>

      <Dialog
        open={confirmDelete !== null}
        onClose={() => setConfirmDelete(null)}
        title="Delete template"
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
          Delete <strong>{confirmDelete?.name}</strong>? This is blocked if any
          course offering still references the template.
        </p>
        {actionErr ? <ErrorText>{actionErr}</ErrorText> : null}
      </Dialog>
    </div>
  );
}

function TemplateFormBody({
  form,
  componentsArray,
  readOnly,
  aat,
  weight,
  actionErr,
}: {
  form: UseFormReturn<TemplateForm>;
  componentsArray: ReturnType<typeof useFieldArray<TemplateForm, "default_components">>;
  readOnly: boolean;
  aat: number;
  weight: number;
  actionErr: string | null;
}) {
  const aatTone: "green" | "amber" | "red" =
    aat > 40 ? "red" : aat > 20 ? "amber" : "green";
  const weightTone: "green" | "amber" =
    Math.abs(weight - 100) < 0.01 ? "green" : "amber";

  return (
    <form className="space-y-3" autoComplete="off">
      <Field label="Name" error={form.formState.errors.name?.message}>
        <Input disabled={readOnly} {...form.register("name")} />
      </Field>
      <Field
        label="Applies to"
        error={form.formState.errors.applies_to_course_type?.message}
      >
        <Select
          disabled={readOnly}
          {...form.register("applies_to_course_type")}
        >
          <option value="theory">theory</option>
          <option value="lab">lab</option>
          <option value="integrated">integrated</option>
          <option value="nptel">nptel</option>
        </Select>
      </Field>
      <Field label="Description">
        <textarea
          rows={2}
          className="w-full rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-zinc-900 disabled:bg-zinc-100"
          disabled={readOnly}
          {...form.register("description")}
        />
      </Field>
      <Field
        label="Validation rules (JSON)"
        error={form.formState.errors.validation_rules_json?.message}
      >
        <textarea
          rows={4}
          className="w-full rounded border border-zinc-300 bg-white px-2 py-1.5 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-zinc-900 disabled:bg-zinc-100"
          disabled={readOnly}
          {...form.register("validation_rules_json")}
        />
      </Field>

      <div className="space-y-2 rounded border border-zinc-200 p-2">
        <div className="flex items-center justify-between text-xs text-zinc-600">
          <span>Default components</span>
          <span className="flex gap-2">
            <Badge tone={aatTone}>AAT {aat.toFixed(1)}%</Badge>
            <Badge tone={weightTone}>weight {weight.toFixed(1)}%</Badge>
          </span>
        </div>
        <div className="max-h-72 space-y-2 overflow-y-auto">
          {componentsArray.fields.map((field, idx) => (
            <div
              key={field.id}
              className="grid grid-cols-12 items-end gap-2 rounded bg-zinc-50 p-2"
            >
              <div className="col-span-3">
                <Select
                  disabled={readOnly}
                  {...form.register(`default_components.${idx}.kind` as const)}
                >
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
                  disabled={readOnly}
                  {...form.register(`default_components.${idx}.label` as const)}
                />
              </div>
              <div className="col-span-2">
                <Input
                  type="number"
                  step="0.5"
                  placeholder="Max"
                  disabled={readOnly}
                  {...form.register(
                    `default_components.${idx}.max_marks` as const,
                  )}
                />
              </div>
              <div className="col-span-2">
                <Input
                  type="number"
                  step="0.5"
                  placeholder="Weight %"
                  disabled={readOnly}
                  {...form.register(
                    `default_components.${idx}.weight_percent` as const,
                  )}
                />
              </div>
              <div className="col-span-1">
                <Input
                  type="number"
                  placeholder="#"
                  disabled={readOnly}
                  {...form.register(
                    `default_components.${idx}.ordinal` as const,
                  )}
                />
              </div>
              <div className="col-span-1 flex justify-end">
                {readOnly ? null : (
                  <Button
                    size="sm"
                    variant="ghost"
                    type="button"
                    onClick={() => componentsArray.remove(idx)}
                  >
                    ×
                  </Button>
                )}
              </div>
            </div>
          ))}
        </div>
        {readOnly ? null : (
          <Button
            size="sm"
            variant="secondary"
            type="button"
            onClick={() =>
              componentsArray.append({
                kind: "cie",
                label: "",
                max_marks: 40,
                weight_percent: 0,
                ordinal: componentsArray.fields.length + 1,
              })
            }
          >
            + Add component
          </Button>
        )}
      </div>
      {actionErr ? <ErrorText>{actionErr}</ErrorText> : null}
    </form>
  );
}
