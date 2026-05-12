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
  Table,
  Td,
  Th,
} from "@/components/ui";

type Department = {
  id: string;
  name: string;
  code: string;
  deleted_at: string | null;
};

const schema = z.object({
  name: z.string().min(1, "required"),
  code: z.string().min(1, "required"),
});
type FormData = z.infer<typeof schema>;

export default function DepartmentsTab() {
  const [items, setItems] = useState<Department[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  async function refresh() {
    setListError(null);
    try {
      const r = await api<Page<Department>>("/departments", {
        query: { limit: 200 },
      });
      setItems(r.items);
    } catch (e) {
      setListError(e instanceof ApiError ? e.message : "load failed");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function onDelete(id: string) {
    if (!confirm("Soft-delete this department?")) return;
    try {
      await api(`/departments/${id}`, { method: "DELETE" });
      await refresh();
    } catch (e) {
      alert(e instanceof ApiError ? e.message : "delete failed");
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-zinc-600">
          {items ? `${items.length} active` : "—"}
        </p>
        <Button onClick={() => setOpen(true)}>Add department</Button>
      </div>

      {listError && <ErrorText>{listError}</ErrorText>}
      {!items && !listError && <Loading />}

      {items && (
        <Card>
          <Table>
            <thead>
              <tr>
                <Th>Code</Th>
                <Th>Name</Th>
                <Th>Status</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {items.length === 0 && (
                <tr>
                  <Td colSpan={4} className="text-center text-zinc-500">
                    No departments yet.
                  </Td>
                </tr>
              )}
              {items.map((d) => (
                <tr key={d.id}>
                  <Td className="font-mono text-xs">{d.code}</Td>
                  <Td>{d.name}</Td>
                  <Td>
                    <Badge tone="green">active</Badge>
                  </Td>
                  <Td className="text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => onDelete(d.id)}
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
        onCreated={async () => {
          setOpen(false);
          await refresh();
        }}
      />
    </div>
  );
}

function CreateDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void | Promise<void>;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    reset,
  } = useForm<FormData>({ resolver: zodResolver(schema) });
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      reset();
      setErr(null);
    }
  }, [open, reset]);

  const onSubmit = handleSubmit(async (values) => {
    setErr(null);
    try {
      await api("/departments", { method: "POST", body: values });
      await onCreated();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "create failed");
    }
  });

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Add department"
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
        <Field label="Code" htmlFor="code" error={errors.code?.message}>
          <Input id="code" placeholder="e.g. CSE" {...register("code")} />
        </Field>
        <Field label="Name" htmlFor="name" error={errors.name?.message}>
          <Input
            id="name"
            placeholder="Computer Science & Engineering"
            {...register("name")}
          />
        </Field>
        <ErrorText>{err}</ErrorText>
      </form>
    </Dialog>
  );
}
