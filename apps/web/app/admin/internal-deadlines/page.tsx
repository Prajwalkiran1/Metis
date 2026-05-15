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

type Deadline = {
  id: string;
  academic_term_id: string;
  academic_term_code: string | null;
  department_id: string | null;
  department_code: string | null;
  course_offering_id: string | null;
  course_code: string | null;
  deadline_at: string;
  kind: "institutional_hard" | "department_soft" | "per_course_freeze";
  set_by_user_id: string;
  set_by_name: string | null;
  is_frozen: boolean;
  frozen_at: string | null;
  frozen_by_user_id: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
};

type AcademicTerm = { id: string; code: string };

const createSchema = z.object({
  academic_term_id: z.string().uuid(),
  deadline_at: z.string().min(1),
  notes: z.string().max(2000).optional(),
});
type CreateForm = z.infer<typeof createSchema>;

const freezeSchema = z.object({
  notes: z.string().max(2000).optional(),
});
type FreezeForm = z.infer<typeof freezeSchema>;

function kindTone(k: Deadline["kind"]): "neutral" | "amber" | "red" {
  if (k === "institutional_hard") return "red";
  if (k === "department_soft") return "amber";
  return "neutral";
}

export default function AdminInternalDeadlinesPage() {
  const [rows, setRows] = useState<Deadline[] | null>(null);
  const [terms, setTerms] = useState<AcademicTerm[]>([]);
  const [termFilter, setTermFilter] = useState("");
  const [kindFilter, setKindFilter] = useState<"" | Deadline["kind"]>("");
  const [err, setErr] = useState<string | null>(null);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [openCreate, setOpenCreate] = useState(false);
  const [openFreeze, setOpenFreeze] = useState<Deadline | null>(null);

  const createForm = useForm<CreateForm>({
    resolver: zodResolver(createSchema),
    defaultValues: {
      academic_term_id: "",
      deadline_at: "",
      notes: "",
    },
  });
  const freezeForm = useForm<FreezeForm>({
    resolver: zodResolver(freezeSchema),
    defaultValues: { notes: "" },
  });

  const reload = useCallback(async () => {
    try {
      const out = await api<Deadline[]>("/workflow/internal-deadlines", {
        query: {
          academic_term_id: termFilter || undefined,
          kind: kindFilter || undefined,
        },
      });
      setRows(out);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "load failed");
    }
  }, [termFilter, kindFilter]);

  const reloadTerms = useCallback(async () => {
    try {
      const t = await api<AcademicTerm[]>("/academic-terms");
      setTerms(t);
    } catch {
      setTerms([]);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);
  useEffect(() => {
    reloadTerms();
  }, [reloadTerms]);

  const institutionalRows = useMemo(
    () => (rows ?? []).filter((r) => r.kind === "institutional_hard"),
    [rows],
  );

  async function onCreate(values: CreateForm) {
    setBusy("create");
    setActionErr(null);
    try {
      await api("/workflow/internal-deadlines", {
        method: "POST",
        body: {
          academic_term_id: values.academic_term_id,
          deadline_at: new Date(values.deadline_at).toISOString(),
          kind: "institutional_hard",
          notes: values.notes || undefined,
        },
      });
      setOpenCreate(false);
      createForm.reset();
      await reload();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "create failed");
    } finally {
      setBusy(null);
    }
  }

  async function onFreeze(d: Deadline, isFrozen: boolean, notes?: string) {
    setBusy(`freeze:${d.id}`);
    setActionErr(null);
    try {
      await api(`/workflow/internal-deadlines/${d.id}/freeze`, {
        method: "POST",
        body: { is_frozen: isFrozen, notes },
      });
      setOpenFreeze(null);
      await reload();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "freeze failed");
    } finally {
      setBusy(null);
    }
  }

  async function onDelete(d: Deadline) {
    setBusy(`delete:${d.id}`);
    setActionErr(null);
    try {
      await api(`/workflow/internal-deadlines/${d.id}`, { method: "DELETE" });
      await reload();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "delete failed");
    } finally {
      setBusy(null);
    }
  }

  if (err) return <ErrorText>{err}</ErrorText>;
  if (rows === null) return <Loading />;

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-lg font-semibold text-zinc-900">
            Internal deadlines
          </h1>
          <p className="text-sm text-zinc-500">
            Institutional hard-stops freeze attendance and marks edits term-wide
            once you flip <em>Freeze now</em>. Department-soft and per-course
            freezes are listed here read-only — HODs and teachers own those.
          </p>
        </div>
        <Button onClick={() => setOpenCreate(true)}>New hard-stop</Button>
      </div>

      <Card className="p-3">
        <div className="flex flex-wrap gap-3">
          <Field label="Term">
            <Select
              value={termFilter}
              onChange={(e) => setTermFilter(e.target.value)}
            >
              <option value="">All</option>
              {terms.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.code}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Kind">
            <Select
              value={kindFilter}
              onChange={(e) =>
                setKindFilter((e.target.value || "") as typeof kindFilter)
              }
            >
              <option value="">All</option>
              <option value="institutional_hard">institutional_hard</option>
              <option value="department_soft">department_soft</option>
              <option value="per_course_freeze">per_course_freeze</option>
            </Select>
          </Field>
        </div>
      </Card>

      {actionErr ? <p className="text-sm text-red-600">{actionErr}</p> : null}

      <Card className="overflow-x-auto">
        {rows.length === 0 ? (
          <p className="px-4 py-6 text-sm text-zinc-500">
            No deadlines in this filter.
          </p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Kind</Th>
                <Th>Term</Th>
                <Th>Scope</Th>
                <Th>Deadline</Th>
                <Th>State</Th>
                <Th>Set by</Th>
                <Th></Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => (
                <tr key={d.id}>
                  <Td>
                    <Badge tone={kindTone(d.kind)}>{d.kind}</Badge>
                  </Td>
                  <Td>{d.academic_term_code ?? d.academic_term_id.slice(0, 8)}</Td>
                  <Td className="text-zinc-700">
                    {d.kind === "institutional_hard"
                      ? "Institution-wide"
                      : d.kind === "department_soft"
                        ? `Dept · ${d.department_code ?? "—"}`
                        : `Offering · ${d.course_code ?? "—"}`}
                  </Td>
                  <Td>{new Date(d.deadline_at).toLocaleString()}</Td>
                  <Td>
                    {d.is_frozen ? (
                      <Badge tone="red">frozen</Badge>
                    ) : (
                      <Badge tone="amber">open</Badge>
                    )}
                  </Td>
                  <Td className="text-zinc-700">{d.set_by_name ?? "—"}</Td>
                  <Td>
                    <div className="flex gap-2">
                      {d.kind === "institutional_hard" ? (
                        <>
                          <Button
                            size="sm"
                            variant={d.is_frozen ? "secondary" : "primary"}
                            onClick={() => {
                              freezeForm.reset({ notes: d.notes ?? "" });
                              setActionErr(null);
                              setOpenFreeze(d);
                            }}
                            disabled={busy === `freeze:${d.id}`}
                          >
                            {d.is_frozen ? "Unfreeze" : "Freeze now"}
                          </Button>
                          {!d.is_frozen ? (
                            <Button
                              size="sm"
                              variant="danger"
                              onClick={() => onDelete(d)}
                              disabled={busy === `delete:${d.id}`}
                            >
                              Delete
                            </Button>
                          ) : null}
                        </>
                      ) : (
                        <span className="text-xs text-zinc-400">
                          read-only
                        </span>
                      )}
                    </div>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      {institutionalRows.length === 0 ? (
        <Card className="border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">
          No institutional hard-stop deadline configured for any term. Add one
          to enable system-wide attendance/marks freeze once the deadline
          lands.
        </Card>
      ) : null}

      <Dialog
        open={openCreate}
        onClose={() => setOpenCreate(false)}
        title="New institutional hard-stop"
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
              {busy === "create" ? "Creating…" : "Create"}
            </Button>
          </>
        }
      >
        <form className="space-y-3">
          <Field
            label="Term"
            error={createForm.formState.errors.academic_term_id?.message}
          >
            <Select {...createForm.register("academic_term_id")}>
              <option value="">— select —</option>
              {terms.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.code}
                </option>
              ))}
            </Select>
          </Field>
          <Field
            label="Deadline (local time)"
            error={createForm.formState.errors.deadline_at?.message}
          >
            <Input
              type="datetime-local"
              {...createForm.register("deadline_at")}
            />
          </Field>
          <Field label="Notes">
            <textarea
              rows={2}
              className="w-full rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-zinc-900"
              {...createForm.register("notes")}
            />
          </Field>
          {actionErr ? <ErrorText>{actionErr}</ErrorText> : null}
        </form>
      </Dialog>

      <Dialog
        open={openFreeze !== null}
        onClose={() => setOpenFreeze(null)}
        title={
          openFreeze?.is_frozen
            ? "Unfreeze institutional deadline"
            : "Freeze institutional deadline"
        }
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => setOpenFreeze(null)}
              disabled={busy?.startsWith("freeze:") ?? false}
            >
              Cancel
            </Button>
            <Button
              variant={openFreeze?.is_frozen ? "primary" : "danger"}
              onClick={freezeForm.handleSubmit((v) =>
                openFreeze && onFreeze(openFreeze, !openFreeze.is_frozen, v.notes),
              )}
              disabled={busy?.startsWith("freeze:") ?? false}
            >
              {openFreeze?.is_frozen ? "Unfreeze" : "Freeze now"}
            </Button>
          </>
        }
      >
        <p className="text-sm text-zinc-700">
          {openFreeze?.is_frozen
            ? "Unfreezing reopens attendance and marks edits for offerings in this term."
            : "Freezing emits the internal_deadline.crossed event and stops all attendance and marks edits across this term."}
        </p>
        <Field label="Notes">
          <textarea
            rows={2}
            className="w-full rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-zinc-900"
            {...freezeForm.register("notes")}
          />
        </Field>
        {actionErr ? <ErrorText>{actionErr}</ErrorText> : null}
      </Dialog>
    </div>
  );
}
