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
type CalendarEntry = {
  id: string;
  entry_date: string;
  kind: "holiday" | "exam" | "event" | "term_start" | "term_end";
  title: string;
  applies_to_department_id: string | null;
  cancels_classes: boolean;
};

const KINDS = ["holiday", "exam", "event", "term_start", "term_end"] as const;

const schema = z.object({
  entry_date: z.string().min(1),
  kind: z.enum(KINDS),
  title: z.string().min(1, "required"),
  applies_to_department_id: z.string().optional(),
  cancels_classes: z.boolean(),
});
type FormData = z.infer<typeof schema>;

export default function CalendarTab() {
  const [items, setItems] = useState<CalendarEntry[] | null>(null);
  const [depts, setDepts] = useState<Department[] | null>(null);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  async function load() {
    setErr(null);
    try {
      const [d, r] = await Promise.all([
        api<Page<Department>>("/departments", { query: { limit: 200 } }),
        api<Page<CalendarEntry>>("/academic-calendar", {
          query: { from: from || undefined, to: to || undefined, limit: 400 },
        }),
      ]);
      setDepts(d.items);
      setItems(r.items);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "load failed");
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [from, to]);

  async function onDelete(id: string) {
    if (!confirm("Soft-delete this entry?")) return;
    try {
      await api(`/academic-calendar/${id}`, { method: "DELETE" });
      await load();
    } catch (e) {
      alert(e instanceof ApiError ? e.message : "delete failed");
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-44">
          <Field label="From">
            <Input
              type="date"
              value={from}
              onChange={(e) => setFrom(e.target.value)}
            />
          </Field>
        </div>
        <div className="w-44">
          <Field label="To">
            <Input
              type="date"
              value={to}
              onChange={(e) => setTo(e.target.value)}
            />
          </Field>
        </div>
        <div className="ml-auto">
          <Button onClick={() => setOpen(true)}>Add entry</Button>
        </div>
      </div>
      {err && <ErrorText>{err}</ErrorText>}
      {!items && !err && <Loading />}
      {items && (
        <Card>
          <Table>
            <thead>
              <tr>
                <Th>Date</Th>
                <Th>Kind</Th>
                <Th>Title</Th>
                <Th>Scope</Th>
                <Th>Cancels classes</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {items.length === 0 && (
                <tr>
                  <Td colSpan={6} className="text-center text-zinc-500">
                    No entries in this window.
                  </Td>
                </tr>
              )}
              {items.map((c) => (
                <tr key={c.id}>
                  <Td className="font-mono text-xs">{c.entry_date}</Td>
                  <Td>
                    <Badge
                      tone={
                        c.kind === "holiday"
                          ? "amber"
                          : c.kind === "exam"
                            ? "red"
                            : "neutral"
                      }
                    >
                      {c.kind}
                    </Badge>
                  </Td>
                  <Td>{c.title}</Td>
                  <Td className="text-xs text-zinc-500">
                    {c.applies_to_department_id
                      ? (depts ?? []).find(
                          (d) => d.id === c.applies_to_department_id,
                        )?.code ?? "dept-only"
                      : "college-wide"}
                  </Td>
                  <Td>
                    {c.cancels_classes ? (
                      <Badge tone="amber">yes</Badge>
                    ) : (
                      <Badge>no</Badge>
                    )}
                  </Td>
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
  } = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: {
      entry_date: "",
      kind: "holiday",
      title: "",
      applies_to_department_id: "",
      cancels_classes: true,
    },
  });
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      reset({
        entry_date: "",
        kind: "holiday",
        title: "",
        applies_to_department_id: "",
        cancels_classes: true,
      });
      setErr(null);
    }
  }, [open, reset]);

  const onSubmit = handleSubmit(async (v) => {
    setErr(null);
    const body: Record<string, unknown> = {
      entry_date: v.entry_date,
      kind: v.kind,
      title: v.title,
      cancels_classes: v.cancels_classes,
    };
    if (v.applies_to_department_id)
      body.applies_to_department_id = v.applies_to_department_id;
    try {
      await api("/academic-calendar", { method: "POST", body });
      await onCreated();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "create failed");
    }
  });

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Add calendar entry"
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
        <div className="grid grid-cols-2 gap-3">
          <Field label="Date" error={errors.entry_date?.message}>
            <Input type="date" {...register("entry_date")} />
          </Field>
          <Field label="Kind" error={errors.kind?.message}>
            <Select {...register("kind")}>
              {KINDS.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <Field label="Title" error={errors.title?.message}>
          <Input placeholder="Independence Day" {...register("title")} />
        </Field>
        <Field label="Scope">
          <Select {...register("applies_to_department_id")}>
            <option value="">College-wide</option>
            {depts.map((d) => (
              <option key={d.id} value={d.id}>
                {d.code} — {d.name}
              </option>
            ))}
          </Select>
        </Field>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-zinc-300"
            {...register("cancels_classes")}
          />
          Cancels classes on this date
        </label>
        <ErrorText>{err}</ErrorText>
      </form>
    </Dialog>
  );
}
