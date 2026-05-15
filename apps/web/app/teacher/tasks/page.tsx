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
  task_type: "invigilation" | "paper_setting" | "evaluation" | "makeup_exam" | "other";
  title: string;
  description: string | null;
  due_at: string | null;
  status: "pending" | "accepted" | "declined" | "completed" | "cancelled";
  decline_reason: string | null;
  created_at: string;
};

const declineSchema = z.object({
  decline_reason: z.string().min(1).max(2000),
});
type DeclineForm = z.infer<typeof declineSchema>;

function statusTone(s: TaskRow["status"]): "neutral" | "green" | "amber" | "red" {
  if (s === "accepted") return "green";
  if (s === "completed") return "green";
  if (s === "pending") return "amber";
  if (s === "declined") return "red";
  return "neutral";
}

export default function TeacherTasksPage() {
  const [tasks, setTasks] = useState<TaskRow[] | null>(null);
  const [filter, setFilter] = useState<"" | TaskRow["status"]>("");
  const [err, setErr] = useState<string | null>(null);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [openDecline, setOpenDecline] = useState<TaskRow | null>(null);

  const declineForm = useForm<DeclineForm>({
    resolver: zodResolver(declineSchema),
    defaultValues: { decline_reason: "" },
  });

  const reload = useCallback(async () => {
    try {
      const rows = await api<TaskRow[]>("/workflow/tasks", {
        query: { mode: "mine", status: filter || undefined },
      });
      setTasks(rows);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "load failed");
    }
  }, [filter]);

  useEffect(() => {
    reload();
  }, [reload]);

  async function transition(t: TaskRow, status: string, decline_reason?: string) {
    setBusy(`${status}:${t.id}`);
    setActionErr(null);
    try {
      await api(`/workflow/tasks/${t.id}/status`, {
        method: "POST",
        body: { status, decline_reason },
      });
      setOpenDecline(null);
      declineForm.reset({ decline_reason: "" });
      await reload();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "update failed");
    } finally {
      setBusy(null);
    }
  }

  if (err) return <ErrorText>{err}</ErrorText>;
  if (tasks === null) return <Loading />;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-zinc-900">My tasks</h1>
        <p className="text-sm text-zinc-500">
          Tasks your HOD has assigned to you. Accept to commit; decline with a
          reason if you can't. Once you've finished the work, mark it complete.
        </p>
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
                <Th>From</Th>
                <Th>Due</Th>
                <Th>Status</Th>
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
                  </Td>
                  <Td>
                    <Badge tone="neutral">{t.task_type}</Badge>
                  </Td>
                  <Td>{t.assigned_by_name ?? t.assigned_by_user_id}</Td>
                  <Td className="text-zinc-600">
                    {t.due_at ? new Date(t.due_at).toLocaleString() : "—"}
                  </Td>
                  <Td>
                    <Badge tone={statusTone(t.status)}>{t.status}</Badge>
                  </Td>
                  <Td>
                    <div className="flex gap-2">
                      {t.status === "pending" ? (
                        <>
                          <Button
                            size="sm"
                            onClick={() => transition(t, "accepted")}
                            disabled={busy === `accepted:${t.id}`}
                          >
                            Accept
                          </Button>
                          <Button
                            size="sm"
                            variant="danger"
                            onClick={() => {
                              declineForm.reset({ decline_reason: "" });
                              setActionErr(null);
                              setOpenDecline(t);
                            }}
                          >
                            Decline
                          </Button>
                        </>
                      ) : null}
                      {t.status === "accepted" ? (
                        <Button
                          size="sm"
                          onClick={() => transition(t, "completed")}
                          disabled={busy === `completed:${t.id}`}
                        >
                          Mark complete
                        </Button>
                      ) : null}
                    </div>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <Dialog
        open={openDecline !== null}
        onClose={() => setOpenDecline(null)}
        title={`Decline · ${openDecline?.title ?? ""}`}
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => setOpenDecline(null)}
              disabled={busy?.startsWith("declined:") ?? false}
            >
              Cancel
            </Button>
            <Button
              variant="danger"
              onClick={declineForm.handleSubmit((v) =>
                openDecline && transition(openDecline, "declined", v.decline_reason),
              )}
              disabled={busy?.startsWith("declined:") ?? false}
            >
              Decline
            </Button>
          </>
        }
      >
        <form className="space-y-3">
          <Field
            label="Reason"
            error={declineForm.formState.errors.decline_reason?.message}
          >
            <textarea
              rows={3}
              className="w-full rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-zinc-900"
              {...declineForm.register("decline_reason")}
            />
          </Field>
          {actionErr ? <ErrorText>{actionErr}</ErrorText> : null}
        </form>
      </Dialog>
    </div>
  );
}
