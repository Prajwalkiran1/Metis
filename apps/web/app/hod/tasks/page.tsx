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

type Status = "pending" | "accepted" | "declined" | "completed" | "cancelled";
type TaskType =
  | "invigilation"
  | "paper_setting"
  | "evaluation"
  | "makeup_exam"
  | "other";

type Assignment = {
  id: string;
  task_id: string;
  assignee_user_id: string;
  assignee_name: string | null;
  status: Status;
  status_updated_at: string | null;
  decline_reason: string | null;
};

type TaskRow = {
  id: string;
  assigned_by_user_id: string;
  assigned_by_name: string | null;
  task_type: TaskType;
  title: string;
  description: string | null;
  due_at: string | null;
  assignments: Assignment[];
  status_counts: Partial<Record<Status, number>>;
  is_complete: boolean;
  created_at: string;
};

type TeacherUser = {
  id: string;
  name: string;
  role: "teacher" | "hod" | "admin" | "student" | "parent";
};

const createSchema = z.object({
  assignee_user_ids: z
    .array(z.string().uuid())
    .min(1, "pick at least one assignee"),
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

function statusTone(s: Status): "neutral" | "green" | "amber" | "red" {
  if (s === "accepted" || s === "completed") return "green";
  if (s === "pending") return "amber";
  if (s === "declined") return "red";
  return "neutral";
}

export default function HodTasksPage() {
  const [tasks, setTasks] = useState<TaskRow[] | null>(null);
  const [teachers, setTeachers] = useState<TeacherUser[]>([]);
  const [filter, setFilter] = useState<"" | Status>("");
  const [err, setErr] = useState<string | null>(null);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [openCreate, setOpenCreate] = useState(false);
  const [picked, setPicked] = useState<Record<string, boolean>>({});

  const createForm = useForm<CreateForm>({
    resolver: zodResolver(createSchema),
    defaultValues: {
      assignee_user_ids: [],
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

  function openCreateDialog() {
    setPicked({});
    createForm.reset();
    setActionErr(null);
    setOpenCreate(true);
  }

  async function onCreate(values: CreateForm) {
    const pickedIds = Object.entries(picked)
      .filter(([, v]) => v)
      .map(([k]) => k);
    if (pickedIds.length === 0) {
      setActionErr("pick at least one assignee");
      return;
    }
    setBusy("create");
    setActionErr(null);
    try {
      await api("/workflow/tasks", {
        method: "POST",
        body: {
          assignee_user_ids: pickedIds,
          task_type: values.task_type,
          title: values.title,
          description: values.description || undefined,
          due_at: values.due_at ? new Date(values.due_at).toISOString() : undefined,
        },
      });
      setOpenCreate(false);
      createForm.reset();
      setPicked({});
      await reload();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "create failed");
    } finally {
      setBusy(null);
    }
  }

  async function onCancelAssignment(assignment: Assignment) {
    setBusy(`cancel:${assignment.id}`);
    setActionErr(null);
    try {
      await api(`/workflow/task-assignments/${assignment.id}/status`, {
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
            duties to one or more teachers in your department. Each assignee
            transitions their own row independently; you can cancel any
            pending/accepted assignment from here.
          </p>
        </div>
        <Button onClick={openCreateDialog}>New task</Button>
      </div>

      <Card className="p-3">
        <div className="flex gap-3">
          <Field label="Status (matches any assignee)">
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
                <Th>Due</Th>
                <Th>Assignees</Th>
                <Th>Aggregate</Th>
                <Th>Created</Th>
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
                  </Td>
                  <Td>
                    <Badge tone="neutral">{t.task_type}</Badge>
                  </Td>
                  <Td className="text-zinc-600">
                    {t.due_at ? new Date(t.due_at).toLocaleString() : "—"}
                  </Td>
                  <Td>
                    <div className="space-y-1.5">
                      {t.assignments.map((a) => (
                        <div
                          key={a.id}
                          className="flex items-center gap-2 text-xs"
                        >
                          <span className="text-zinc-900">
                            {a.assignee_name ?? a.assignee_user_id.slice(0, 8)}
                          </span>
                          <Badge tone={statusTone(a.status)}>{a.status}</Badge>
                          {a.decline_reason ? (
                            <span
                              className="text-red-700"
                              title={a.decline_reason}
                            >
                              ({a.decline_reason.slice(0, 40)})
                            </span>
                          ) : null}
                          {a.status === "pending" || a.status === "accepted" ? (
                            <button
                              type="button"
                              className="text-red-700 underline disabled:text-zinc-400"
                              disabled={busy === `cancel:${a.id}`}
                              onClick={() => onCancelAssignment(a)}
                            >
                              cancel
                            </button>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  </Td>
                  <Td>
                    <div className="flex flex-wrap gap-1">
                      {(["pending", "accepted", "completed", "declined", "cancelled"] as Status[])
                        .filter((s) => (t.status_counts[s] ?? 0) > 0)
                        .map((s) => (
                          <Badge key={s} tone={statusTone(s)}>
                            {t.status_counts[s]} {s}
                          </Badge>
                        ))}
                      {t.is_complete ? (
                        <Badge tone="green">done</Badge>
                      ) : null}
                    </div>
                  </Td>
                  <Td className="text-zinc-500">
                    {new Date(t.created_at).toLocaleDateString()}
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
            label="Assignees (pick one or more)"
            error={
              Object.values(picked).every((v) => !v)
                ? createForm.formState.errors.assignee_user_ids?.message
                : undefined
            }
          >
            <div className="max-h-48 overflow-y-auto rounded border border-zinc-300 bg-white p-2 text-sm">
              {teachers.length === 0 ? (
                <p className="text-xs text-zinc-500">No teachers loaded.</p>
              ) : (
                teachers.map((t) => (
                  <label
                    key={t.id}
                    className="flex items-center gap-2 py-0.5"
                  >
                    <input
                      type="checkbox"
                      checked={!!picked[t.id]}
                      onChange={(e) =>
                        setPicked((p) => ({ ...p, [t.id]: e.target.checked }))
                      }
                    />
                    <span>
                      {t.name}{" "}
                      <span className="text-xs text-zinc-500">({t.role})</span>
                    </span>
                  </label>
                ))
              )}
            </div>
            <p className="mt-1 text-xs text-zinc-500">
              {Object.values(picked).filter(Boolean).length} selected
            </p>
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
