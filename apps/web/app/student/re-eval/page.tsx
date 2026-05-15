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

type ReEval = {
  id: string;
  course_offering_id: string | null;
  course_code: string | null;
  requested_at: string;
  status: "requested" | "processing" | "completed" | "rejected";
  original_marks: number | null;
  revised_marks: number | null;
  outcome: string | null;
  reason: string | null;
};

type Offering = {
  course_offering_id: string;
  course_code: string;
  course_title: string;
};

type StudentRegistrationView = {
  semester_setup_id: string | null;
  mandatory_courses: {
    course_offering_id: string;
    course_code: string;
    course_title: string;
  }[];
  groups: {
    options: {
      option_id: string;
      course_id: string;
      course_code: string;
      course_title: string;
    }[];
    chosen_option_id: string | null;
  }[];
};

const requestSchema = z.object({
  course_offering_id: z.string().uuid(),
  reason: z.string().min(1).max(2000),
});
type RequestForm = z.infer<typeof requestSchema>;

function statusTone(s: ReEval["status"]): "green" | "amber" | "red" | "neutral" {
  if (s === "completed") return "green";
  if (s === "rejected") return "red";
  if (s === "requested" || s === "processing") return "amber";
  return "neutral";
}

export default function StudentReEvalPage() {
  const [requests, setRequests] = useState<ReEval[] | null>(null);
  const [offerings, setOfferings] = useState<Offering[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [openReq, setOpenReq] = useState(false);

  const form = useForm<RequestForm>({
    resolver: zodResolver(requestSchema),
    defaultValues: { course_offering_id: "", reason: "" },
  });

  const reload = useCallback(async () => {
    try {
      const rows = await api<ReEval[]>("/workflow/re-evaluations", {
        query: { mine: true },
      });
      setRequests(rows);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "load failed");
    }
  }, []);

  const reloadOfferings = useCallback(async () => {
    try {
      const view = await api<StudentRegistrationView>("/student/registration");
      const offs: Offering[] = view.mandatory_courses.map((c) => ({
        course_offering_id: c.course_offering_id,
        course_code: c.course_code,
        course_title: c.course_title,
      }));
      setOfferings(offs);
    } catch {
      setOfferings([]);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);
  useEffect(() => {
    reloadOfferings();
  }, [reloadOfferings]);

  async function onCreate(values: RequestForm) {
    setBusy("create");
    setActionErr(null);
    try {
      await api("/workflow/re-evaluations", {
        method: "POST",
        body: values,
      });
      setOpenReq(false);
      form.reset();
      await reload();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "request failed");
    } finally {
      setBusy(null);
    }
  }

  if (err) return <ErrorText>{err}</ErrorText>;
  if (requests === null) return <Loading />;

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-lg font-semibold text-zinc-900">
            Re-evaluation
          </h1>
          <p className="text-sm text-zinc-500">
            Request a re-evaluation after SEE marks are released. The revised
            mark can only improve or hold your score — never reduce it.
          </p>
        </div>
        <Button onClick={() => setOpenReq(true)}>New request</Button>
      </div>

      {actionErr ? <p className="text-sm text-red-600">{actionErr}</p> : null}

      <Card className="overflow-x-auto">
        {requests.length === 0 ? (
          <p className="px-4 py-6 text-sm text-zinc-500">
            No re-evaluation requests yet.
          </p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Course</Th>
                <Th>Requested</Th>
                <Th>Original</Th>
                <Th>Revised</Th>
                <Th>Status</Th>
                <Th>Outcome</Th>
                <Th>Reason</Th>
              </tr>
            </thead>
            <tbody>
              {requests.map((r) => (
                <tr key={r.id}>
                  <Td className="font-medium">{r.course_code ?? "—"}</Td>
                  <Td className="text-zinc-500">
                    {new Date(r.requested_at).toLocaleDateString()}
                  </Td>
                  <Td>
                    {r.original_marks !== null
                      ? r.original_marks.toFixed(1)
                      : "—"}
                  </Td>
                  <Td>
                    {r.revised_marks !== null
                      ? r.revised_marks.toFixed(1)
                      : "—"}
                  </Td>
                  <Td>
                    <Badge tone={statusTone(r.status)}>{r.status}</Badge>
                  </Td>
                  <Td>{r.outcome ?? "—"}</Td>
                  <Td className="max-w-[260px] truncate text-xs text-zinc-600">
                    {r.reason ?? "—"}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <Dialog
        open={openReq}
        onClose={() => setOpenReq(false)}
        title="Request re-evaluation"
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => setOpenReq(false)}
              disabled={busy === "create"}
            >
              Cancel
            </Button>
            <Button
              onClick={form.handleSubmit(onCreate)}
              disabled={busy === "create"}
            >
              {busy === "create" ? "Submitting…" : "Submit"}
            </Button>
          </>
        }
      >
        <form className="space-y-3">
          <Field
            label="Course"
            error={form.formState.errors.course_offering_id?.message}
          >
            <Select {...form.register("course_offering_id")}>
              <option value="">— pick a course —</option>
              {offerings.map((o) => (
                <option key={o.course_offering_id} value={o.course_offering_id}>
                  {o.course_code} — {o.course_title}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Reason" error={form.formState.errors.reason?.message}>
            <textarea
              rows={3}
              className="w-full rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-zinc-900"
              {...form.register("reason")}
            />
          </Field>
          {actionErr ? <ErrorText>{actionErr}</ErrorText> : null}
        </form>
      </Dialog>
    </div>
  );
}
