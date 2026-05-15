"use client";

import { useCallback, useEffect, useState } from "react";
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

type TaskRow = {
  id: string;
  assigned_by_user_id: string;
  assigned_by_name: string | null;
  assigned_to_user_id: string;
  assigned_to_name: string | null;
  task_type: "invigilation" | "paper_setting" | "evaluation" | "makeup_exam" | "other";
  title: string;
  description: string | null;
  due_at: string | null;
  status: "pending" | "accepted" | "declined" | "completed" | "cancelled";
  decline_reason: string | null;
  created_at: string;
};

type TeacherUser = {
  id: string;
  name: string;
  role: "teacher" | "hod" | "admin" | "student" | "parent";
};

const createSchema = z.object({
  assigned_to_user_id: z.string().uuid(),
  task_type: z.enum([
    "invigilation",
    "paper_setting",
    "evaluation",
    "makeup_exam",
    "other",
  ]),
  title: z.string().min(1).max(200),
  description: z.string().max(4000).optional(),
  due_at: z.string().optional().or(z.literal("")),
});
type CreateForm = z.infer<typeof createSchema>;

function statusTone(s: TaskRow["status"]): "neutral" | "green" | "amber" | "red" {
  if (s === "accepted") return "green";
  if (s === "completed") return "green";
  if (s === "pending") return "amber";
  if (s === "declined") return "red";
  return "neutral";
}

export default function HodTasksPage() {
  const [tasks, setTasks] = useState<TaskRow[] | null>(null);
  const [teachers, setTeachers] = useState<TeacherUser[]>([]);
  const [filter, setFilter] = useState<"" | TaskRow["status"]>("");
  const [err, setErr] = useState<string | null>(null);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [openCreate, setOpenCreate] = useState(false);

  const createForm = useForm<CreateForm>({
    resolver: zodResolver(createSchema),
    defaultValues: {
      assigned_to_user_id: "",
      task_type: "invigilation",
      title: "",
      description: "",
      due_at: "",
    },
  });

  const reload = useCallback(async () => {
    try {
      const rows = await api<TaskRow[]>("/workflow/tasks", {
        query: { mode: "department", status: filter || undefined },
      });
      setTasks(rows);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "load failed");
    }
  }, [filter]);

  const reloadTeachers = useCallback(async () => {
    try {
      const t = await api<{ items: TeacherUser[] }>("/users", {
        query: { role: "teacher", limit: 200 },
      });
      const h = await api<{ items: TeacherUser[] }>("/users", {
        query: { role: "hod", limit: 50 },
      });
      setTeachers([...(t.items ?? []), ...(h.items ?? [])]);
    } catch {
      setTeachers([]);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);
  useEffect(() => {
    reloadTeachers();
  }, [reloadTeachers]);

  async function onCreate(values: CreateForm) {
    setBusy("create");
    setActionErr(null);
    try {
      await api("/workflow/tasks", {
        method: "POST",
        body: {
          assigned_to_user_id: values.assigned_to_user_id,
          task_type: values.task_type,
          title: values.title,
          description: values.description || undefined,
          due_at: values.due_at ? new Date(values.due_at).toISOString() : undefined,
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

  async function onCancel(t: TaskRow) {
    setBusy(`cancel:${t.id}`);
    setActionErr(null);
    try {
      await api(`/workflow/tasks/${t.id}/status`, {
        method: "POST",
        body: { status: "cancelled" },
      });
      await reload();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "cancel failed");
    } finally {
      setBusy(null);
    }
  }

  if (err) return <ErrorText>{err}</ErrorText>;
  if (tasks === null) return <Loading />;

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-lg font-semibold text-zinc-900">Tasks</h1>
          <p className="text-sm text-zinc-500">
            Assign invigilation, paper-setting, evaluation, and makeup-exam
            duties to teachers in your department. Cancel pending tasks here;
            accept/decline/complete live on the teacher's task page.
          </p>
        </div>
        <Button onClick={() => setOpenCreate(true)}>New task</Button>
      </div>

      <Card className="p-3">
        <div className="flex gap-3">
          <Field label="Status">
            <Select
              value={filter}
              onChange={(e) =>
                setFilter((e.target.value || "") as typeof filter)
              }
            >
              <option value="">All</option>
              <option value="pending">pending</option>
              <option value="accepted">accepted</option>
              <option value="declined">declined</option>
              <option value="completed">completed</option>
              <option value="cancelled">cancelled</option>
            </Select>
          </Field>
        </div>
      </Card>

      {actionErr ? <p className="text-sm text-red-600">{actionErr}</p> : null}

      <Card className="overflow-x-auto">
        {tasks.length === 0 ? (
          <p className="px-4 py-6 text-sm text-zinc-500">
            No tasks in this filter.
          </p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Title</Th>
                <Th>Type</Th>
                <Th>Assigned to</Th>
                <Th>Due</Th>
                <Th>Status</Th>
                <Th>Created</Th>
                <Th></Th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((t) => (
                <tr key={t.id}>
                  <Td>
                    <div className="font-medium">{t.title}</div>
                    {t.description ? (
                      <div className="max-w-[280px] truncate text-xs text-zinc-500">
                        {t.description}
                      </div>
                    ) : null}
                    {t.decline_reason ? (
                      <div className="mt-1 text-xs text-red-700">
                        Declined: {t.decline_reason}
                      </div>
                    ) : null}
                  </Td>
                  <Td>
                    <Badge tone="neutral">{t.task_type}</Badge>
                  </Td>
                  <Td>{t.assigned_to_name ?? t.assigned_to_user_id}</Td>
                  <Td className="text-zinc-600">
                    {t.due_at ? new Date(t.due_at).toLocaleString() : "—"}
                  </Td>
                  <Td>
                    <Badge tone={statusTone(t.status)}>{t.status}</Badge>
                  </Td>
                  <Td className="text-zinc-500">
                    {new Date(t.created_at).toLocaleDateString()}
                  </Td>
                  <Td>
                    {t.status === "pending" || t.status === "accepted" ? (
                      <Button
                        size="sm"
                        variant="danger"
                        onClick={() => onCancel(t)}
                        disabled={busy === `cancel:${t.id}`}
                      >
                        Cancel
                      </Button>
                    ) : null}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <Dialog
        open={openCreate}
        onClose={() => setOpenCreate(false)}
        title="New task"
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
            label="Assign to"
            error={createForm.formState.errors.assigned_to_user_id?.message}
          >
            <Select {...createForm.register("assigned_to_user_id")}>
              <option value="">— pick teacher —</option>
              {teachers.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name} ({t.role})
                </option>
              ))}
            </Select>
          </Field>
          <Field
            label="Type"
            error={createForm.formState.errors.task_type?.message}
          >
            <Select {...createForm.register("task_type")}>
              <option value="invigilation">invigilation</option>
              <option value="paper_setting">paper_setting</option>
              <option value="evaluation">evaluation</option>
              <option value="makeup_exam">makeup_exam</option>
              <option value="other">other</option>
            </Select>
          </Field>
          <Field label="Title" error={createForm.formState.errors.title?.message}>
            <Input {...createForm.register("title")} />
          </Field>
          <Field label="Description">
            <textarea
              rows={3}
              className="w-full rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-zinc-900"
              {...createForm.register("description")}
            />
          </Field>
          <Field label="Due (optional)">
            <Input type="datetime-local" {...createForm.register("due_at")} />
          </Field>
          {actionErr ? <ErrorText>{actionErr}</ErrorText> : null}
        </form>
      </Dialog>
    </div>
  );
}
