"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
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

type SetupState = "draft" | "published" | "active" | "archived";

type SemesterSetup = {
  id: string;
  college_id: string;
  department_id: string;
  academic_term_id: string;
  state: SetupState;
  drafted_by_user_id: string;
  published_at: string | null;
  archived_at: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
};

type AcademicTerm = {
  id: string;
  code: string;
  term_type: "regular" | "fast_track";
  starts_on: string | null;
  ends_on: string | null;
};

function stateTone(s: SetupState): "neutral" | "green" | "amber" | "red" {
  if (s === "active" || s === "published") return "green";
  if (s === "draft") return "amber";
  if (s === "archived") return "neutral";
  return "neutral";
}

const newSetupSchema = z.object({
  academic_term_id: z.string().uuid("pick a term"),
  notes: z.string().max(2000).optional(),
});
type NewSetupForm = z.infer<typeof newSetupSchema>;

export default function SemesterSetupListPage() {
  const router = useRouter();
  const [setups, setSetups] = useState<SemesterSetup[] | null>(null);
  const [terms, setTerms] = useState<AcademicTerm[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [openNew, setOpenNew] = useState(false);
  const [creating, setCreating] = useState(false);
  const [formErr, setFormErr] = useState<string | null>(null);

  const form = useForm<NewSetupForm>({
    resolver: zodResolver(newSetupSchema),
    defaultValues: { academic_term_id: "", notes: "" },
  });

  async function reload() {
    try {
      const [setupRows, termRows] = await Promise.all([
        api<SemesterSetup[]>("/workflow/semester-setups"),
        api<AcademicTerm[]>("/academic-terms").catch(() => [] as AcademicTerm[]),
      ]);
      setSetups(setupRows);
      setTerms(termRows);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "load failed");
    }
  }

  useEffect(() => {
    reload();
  }, []);

  const termsWithoutSetup = useMemo(() => {
    const taken = new Set((setups ?? []).map((s) => s.academic_term_id));
    return terms.filter((t) => !taken.has(t.id));
  }, [setups, terms]);

  async function onCreate(values: NewSetupForm) {
    setFormErr(null);
    setCreating(true);
    try {
      // The HOD's department comes from their session — server resolves it
      // via require_hod, but the API still needs department_id in the body.
      const dash = await api<{ department: { id: string } }>("/hod/dashboard");
      const created = await api<SemesterSetup>("/workflow/semester-setups", {
        method: "POST",
        body: {
          department_id: dash.department.id,
          academic_term_id: values.academic_term_id,
          notes: values.notes || undefined,
        },
      });
      setOpenNew(false);
      form.reset({ academic_term_id: "", notes: "" });
      router.push(`/hod/semester-setup/${created.id}`);
    } catch (e) {
      setFormErr(e instanceof ApiError ? e.message : "create failed");
    } finally {
      setCreating(false);
    }
  }

  if (err) return <ErrorText>{err}</ErrorText>;
  if (setups === null) return <Loading />;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-zinc-900">
            Semester setups
          </h1>
          <p className="text-sm text-zinc-500">
            Draft and publish the structure of a semester for your department.
            Admins are notified on publish but do not approve.
          </p>
        </div>
        <Button
          onClick={() => {
            setFormErr(null);
            form.reset({ academic_term_id: "", notes: "" });
            setOpenNew(true);
          }}
          disabled={termsWithoutSetup.length === 0}
          title={
            termsWithoutSetup.length === 0
              ? "All terms already have a setup"
              : undefined
          }
        >
          New setup
        </Button>
      </div>

      <Card className="overflow-x-auto">
        {setups.length === 0 ? (
          <p className="px-4 py-6 text-sm text-zinc-500">
            No setups yet. Click <em>New setup</em> to draft one for an
            academic term.
          </p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Term</Th>
                <Th>State</Th>
                <Th>Published</Th>
                <Th>Last edit</Th>
                <Th>Notes</Th>
                <Th></Th>
              </tr>
            </thead>
            <tbody>
              {setups.map((s) => {
                const term = terms.find((t) => t.id === s.academic_term_id);
                return (
                  <tr key={s.id}>
                    <Td className="font-medium">{term?.code ?? "—"}</Td>
                    <Td>
                      <Badge tone={stateTone(s.state)}>{s.state}</Badge>
                    </Td>
                    <Td className="text-zinc-600">
                      {s.published_at
                        ? new Date(s.published_at).toLocaleString()
                        : "—"}
                    </Td>
                    <Td className="text-zinc-600">
                      {new Date(s.updated_at).toLocaleString()}
                    </Td>
                    <Td className="max-w-[300px] truncate text-zinc-600">
                      {s.notes ?? ""}
                    </Td>
                    <Td>
                      <Link
                        href={`/hod/semester-setup/${s.id}`}
                        className="text-zinc-900 underline"
                      >
                        Open
                      </Link>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}
      </Card>

      <Dialog
        open={openNew}
        onClose={() => setOpenNew(false)}
        title="New semester setup"
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => setOpenNew(false)}
              disabled={creating}
            >
              Cancel
            </Button>
            <Button onClick={form.handleSubmit(onCreate)} disabled={creating}>
              {creating ? "Creating…" : "Create draft"}
            </Button>
          </>
        }
      >
        <form className="space-y-3" onSubmit={form.handleSubmit(onCreate)}>
          <Field
            label="Academic term"
            error={form.formState.errors.academic_term_id?.message}
          >
            <Select {...form.register("academic_term_id")}>
              <option value="">— select —</option>
              {termsWithoutSetup.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.code}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Notes (optional)">
            <textarea
              className="w-full rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-zinc-900"
              rows={3}
              {...form.register("notes")}
            />
          </Field>
          {formErr ? <ErrorText>{formErr}</ErrorText> : null}
        </form>
      </Dialog>
    </div>
  );
}
