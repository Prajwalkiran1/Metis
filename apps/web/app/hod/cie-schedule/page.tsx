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

type SetupList = {
  id: string;
  state: "draft" | "published" | "active" | "archived";
  academic_term_id: string;
};

type CourseAssignment = {
  id: string;
  course_code: string;
  course_title: string;
  course_type: "theory" | "lab" | "integrated" | "nptel";
  section_name: string;
};

type SetupDetail = {
  id: string;
  courses: CourseAssignment[];
};

type CIEEntry = {
  id: string;
  course_offering_id: string;
  cie_number: number;
  scheduled_at: string;
  duration_minutes: number;
  room_id: string | null;
  room_code: string | null;
  notes: string | null;
  is_published: boolean;
  published_at: string | null;
};

type AcademicTerm = { id: string; code: string };
type Room = { id: string; code: string };

const createSchema = z.object({
  cie_number: z.coerce.number().int().min(1).max(3),
  scheduled_at: z.string().min(1),
  duration_minutes: z.coerce.number().int().min(15).max(300),
  room_id: z.string().uuid().optional().or(z.literal("")),
  notes: z.string().max(2000).optional(),
});
type CreateForm = z.infer<typeof createSchema>;

function isoLocalToZ(s: string): string {
  return new Date(s).toISOString();
}
function toLocal(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function HodCIESchedulePage() {
  const [setups, setSetups] = useState<SetupList[] | null>(null);
  const [terms, setTerms] = useState<AcademicTerm[]>([]);
  const [setupId, setSetupId] = useState("");
  const [setupDetail, setSetupDetail] = useState<SetupDetail | null>(null);
  const [offeringId, setOfferingId] = useState("");
  const [entries, setEntries] = useState<CIEEntry[] | null>(null);
  const [rooms, setRooms] = useState<Room[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [openCreate, setOpenCreate] = useState<number | null>(null); // CIE number to pre-fill
  const [confirmDelete, setConfirmDelete] = useState<CIEEntry | null>(null);

  const createForm = useForm<CreateForm>({
    resolver: zodResolver(createSchema),
    defaultValues: {
      cie_number: 1,
      scheduled_at: "",
      duration_minutes: 90,
      room_id: "",
      notes: "",
    },
  });

  const reloadSetups = useCallback(async () => {
    try {
      const [all, termRows] = await Promise.all([
        api<SetupList[]>("/workflow/semester-setups"),
        api<AcademicTerm[]>("/academic-terms").catch(() => [] as AcademicTerm[]),
      ]);
      const usable = all.filter((s) => s.state !== "draft");
      setSetups(usable);
      setTerms(termRows);
      if (usable.length > 0 && !setupId) setSetupId(usable[0].id);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "load failed");
    }
  }, [setupId]);

  const reloadSetupDetail = useCallback(async () => {
    if (!setupId) return;
    try {
      const d = await api<SetupDetail>(`/workflow/semester-setups/${setupId}`);
      setSetupDetail(d);
      if (d.courses.length > 0 && !offeringId) setOfferingId(d.courses[0].id);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "load failed");
    }
  }, [setupId, offeringId]);

  const reloadEntries = useCallback(async () => {
    if (!offeringId) {
      setEntries([]);
      return;
    }
    try {
      const rows = await api<CIEEntry[]>(
        `/workflow/course-offerings/${offeringId}/cie-schedule`,
      );
      setEntries(rows);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "load failed");
    }
  }, [offeringId]);

  const reloadRooms = useCallback(async () => {
    try {
      const page = await api<{ items: Room[] }>("/rooms", {
        query: { limit: 200 },
      }).catch(() => ({ items: [] as Room[] }));
      setRooms(page.items ?? []);
    } catch {
      setRooms([]);
    }
  }, []);

  useEffect(() => {
    reloadSetups();
  }, [reloadSetups]);
  useEffect(() => {
    reloadSetupDetail();
  }, [reloadSetupDetail]);
  useEffect(() => {
    reloadEntries();
  }, [reloadEntries]);
  useEffect(() => {
    reloadRooms();
  }, [reloadRooms]);

  const allPublished = useMemo(() => {
    if (!entries || entries.length === 0) return false;
    return entries.every((e) => e.is_published);
  }, [entries]);

  const missingNumbers = useMemo(() => {
    if (!entries) return [1, 2, 3];
    const present = new Set(entries.map((e) => e.cie_number));
    return [1, 2, 3].filter((n) => !present.has(n));
  }, [entries]);

  async function onCreate(values: CreateForm) {
    if (!offeringId) return;
    setBusy("create");
    setActionErr(null);
    try {
      await api(
        `/workflow/course-offerings/${offeringId}/cie-schedule`,
        {
          method: "POST",
          body: {
            cie_number: values.cie_number,
            scheduled_at: isoLocalToZ(values.scheduled_at),
            duration_minutes: values.duration_minutes,
            room_id: values.room_id || undefined,
            notes: values.notes || undefined,
          },
        },
      );
      setOpenCreate(null);
      await reloadEntries();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "create failed");
    } finally {
      setBusy(null);
    }
  }

  async function onPatchEntry(
    cie: CIEEntry,
    values: { scheduled_at: string; duration_minutes: number; room_id: string },
  ) {
    setBusy(`patch:${cie.id}`);
    setActionErr(null);
    try {
      await api(`/workflow/cie-schedule/${cie.id}`, {
        method: "PATCH",
        body: {
          scheduled_at: isoLocalToZ(values.scheduled_at),
          duration_minutes: values.duration_minutes,
          room_id: values.room_id || undefined,
        },
      });
      await reloadEntries();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "save failed");
    } finally {
      setBusy(null);
    }
  }

  async function onDelete(cie: CIEEntry) {
    setBusy(`delete:${cie.id}`);
    setActionErr(null);
    try {
      await api(`/workflow/cie-schedule/${cie.id}`, { method: "DELETE" });
      setConfirmDelete(null);
      await reloadEntries();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "delete failed");
    } finally {
      setBusy(null);
    }
  }

  async function onPublishToggle(publish: boolean) {
    if (!offeringId) return;
    setBusy(publish ? "publish" : "unpublish");
    setActionErr(null);
    try {
      await api(
        `/workflow/course-offerings/${offeringId}/cie-schedule/publish`,
        { method: "POST", body: { publish } },
      );
      await reloadEntries();
    } catch (e) {
      setActionErr(e instanceof ApiError ? e.message : "publish failed");
    } finally {
      setBusy(null);
    }
  }

  if (err) return <ErrorText>{err}</ErrorText>;
  if (setups === null) return <Loading />;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-zinc-900">CIE schedule</h1>
        <p className="text-sm text-zinc-500">
          Schedule CIE-1, CIE-2, CIE-3 per course offering. Publish makes the
          schedule visible to students (read-only — they see it under each
          course detail).
        </p>
      </div>

      {setups.length === 0 ? (
        <Card>
          <p className="px-4 py-6 text-sm text-zinc-500">
            No published setups yet.
          </p>
        </Card>
      ) : (
        <Card className="p-4">
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Semester setup">
              <Select
                value={setupId}
                onChange={(e) => {
                  setSetupId(e.target.value);
                  setOfferingId("");
                  setEntries(null);
                }}
              >
                {setups.map((s) => {
                  const term = terms.find((t) => t.id === s.academic_term_id);
                  return (
                    <option key={s.id} value={s.id}>
                      {term?.code ?? s.id.slice(0, 8)} · {s.state}
                    </option>
                  );
                })}
              </Select>
            </Field>
            <Field label="Offering">
              <Select
                value={offeringId}
                onChange={(e) => setOfferingId(e.target.value)}
                disabled={!setupDetail || setupDetail.courses.length === 0}
              >
                <option value="">— select —</option>
                {(setupDetail?.courses ?? []).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.course_code} ({c.course_type}) · {c.section_name}
                  </option>
                ))}
              </Select>
            </Field>
            <div className="ml-auto flex items-center gap-2">
              {allPublished ? (
                <Button
                  variant="secondary"
                  onClick={() => onPublishToggle(false)}
                  disabled={busy === "unpublish"}
                >
                  Unpublish all
                </Button>
              ) : (
                <Button
                  onClick={() => onPublishToggle(true)}
                  disabled={!entries || entries.length === 0 || busy === "publish"}
                >
                  Publish all
                </Button>
              )}
            </div>
          </div>
        </Card>
      )}

      {actionErr ? <p className="text-sm text-red-600">{actionErr}</p> : null}

      {offeringId ? (
        <Card className="overflow-x-auto">
          <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-3">
            <h2 className="text-sm font-semibold text-zinc-900">
              CIE entries
            </h2>
            <div className="flex gap-2">
              {missingNumbers.map((n) => (
                <Button
                  key={n}
                  size="sm"
                  variant="secondary"
                  onClick={() => {
                    createForm.reset({
                      cie_number: n,
                      scheduled_at: "",
                      duration_minutes: 90,
                      room_id: "",
                      notes: "",
                    });
                    setActionErr(null);
                    setOpenCreate(n);
                  }}
                  disabled={allPublished}
                >
                  + CIE-{n}
                </Button>
              ))}
            </div>
          </div>
          {entries === null ? (
            <Loading />
          ) : entries.length === 0 ? (
            <p className="px-4 py-6 text-sm text-zinc-500">
              No CIE entries yet. Use the buttons above to add CIE-1/2/3.
            </p>
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>CIE</Th>
                  <Th>Scheduled</Th>
                  <Th>Duration</Th>
                  <Th>Room</Th>
                  <Th>Status</Th>
                  <Th></Th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e) => (
                  <CIERow
                    key={e.id}
                    entry={e}
                    rooms={rooms}
                    allPublished={allPublished}
                    onPatch={(v) => onPatchEntry(e, v)}
                    onDelete={() => setConfirmDelete(e)}
                  />
                ))}
              </tbody>
            </Table>
          )}
        </Card>
      ) : null}

      <Dialog
        open={openCreate !== null}
        onClose={() => setOpenCreate(null)}
        title={`Add CIE-${openCreate ?? ""}`}
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => setOpenCreate(null)}
              disabled={busy === "create"}
            >
              Cancel
            </Button>
            <Button
              onClick={createForm.handleSubmit(onCreate)}
              disabled={busy === "create"}
            >
              {busy === "create" ? "Adding…" : "Add"}
            </Button>
          </>
        }
      >
        <form className="space-y-3">
          <Field
            label="CIE number"
            error={createForm.formState.errors.cie_number?.message}
          >
            <Input type="number" {...createForm.register("cie_number")} />
          </Field>
          <Field
            label="Scheduled (local time)"
            error={createForm.formState.errors.scheduled_at?.message}
          >
            <Input
              type="datetime-local"
              {...createForm.register("scheduled_at")}
            />
          </Field>
          <Field
            label="Duration (minutes)"
            error={createForm.formState.errors.duration_minutes?.message}
          >
            <Input
              type="number"
              {...createForm.register("duration_minutes")}
            />
          </Field>
          <Field label="Room">
            <Select {...createForm.register("room_id")}>
              <option value="">— none —</option>
              {rooms.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.code}
                </option>
              ))}
            </Select>
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
        open={confirmDelete !== null}
        onClose={() => setConfirmDelete(null)}
        title="Delete CIE entry"
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => setConfirmDelete(null)}
              disabled={busy?.startsWith("delete:") ?? false}
            >
              Cancel
            </Button>
            <Button
              variant="danger"
              onClick={() => confirmDelete && onDelete(confirmDelete)}
              disabled={busy?.startsWith("delete:") ?? false}
            >
              Delete
            </Button>
          </>
        }
      >
        <p className="text-sm text-zinc-700">
          Delete CIE-{confirmDelete?.cie_number}? Published CIEs can't be
          deleted — unpublish all first.
        </p>
      </Dialog>
    </div>
  );
}

function CIERow({
  entry,
  rooms,
  allPublished,
  onPatch,
  onDelete,
}: {
  entry: CIEEntry;
  rooms: Room[];
  allPublished: boolean;
  onPatch: (v: {
    scheduled_at: string;
    duration_minutes: number;
    room_id: string;
  }) => void;
  onDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [vals, setVals] = useState({
    scheduled_at: toLocal(entry.scheduled_at),
    duration_minutes: entry.duration_minutes,
    room_id: entry.room_id ?? "",
  });
  useEffect(() => {
    setVals({
      scheduled_at: toLocal(entry.scheduled_at),
      duration_minutes: entry.duration_minutes,
      room_id: entry.room_id ?? "",
    });
  }, [entry.id, entry.scheduled_at, entry.duration_minutes, entry.room_id]);

  return (
    <tr>
      <Td className="font-medium">CIE-{entry.cie_number}</Td>
      <Td>
        {editing && !entry.is_published ? (
          <Input
            type="datetime-local"
            value={vals.scheduled_at}
            onChange={(e) =>
              setVals((s) => ({ ...s, scheduled_at: e.target.value }))
            }
          />
        ) : (
          new Date(entry.scheduled_at).toLocaleString()
        )}
      </Td>
      <Td>
        {editing && !entry.is_published ? (
          <Input
            type="number"
            value={vals.duration_minutes}
            onChange={(e) =>
              setVals((s) => ({
                ...s,
                duration_minutes: Number(e.target.value),
              }))
            }
            className="max-w-[80px]"
          />
        ) : (
          `${entry.duration_minutes} min`
        )}
      </Td>
      <Td>
        {editing && !entry.is_published ? (
          <Select
            value={vals.room_id}
            onChange={(e) =>
              setVals((s) => ({ ...s, room_id: e.target.value }))
            }
          >
            <option value="">— none —</option>
            {rooms.map((r) => (
              <option key={r.id} value={r.id}>
                {r.code}
              </option>
            ))}
          </Select>
        ) : (
          entry.room_code ?? "—"
        )}
      </Td>
      <Td>
        {entry.is_published ? (
          <Badge tone="green">published</Badge>
        ) : (
          <Badge tone="amber">draft</Badge>
        )}
      </Td>
      <Td>
        <div className="flex gap-2">
          {editing ? (
            <>
              <Button
                size="sm"
                onClick={() => {
                  onPatch(vals);
                  setEditing(false);
                }}
              >
                Save
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setEditing(false)}
              >
                Cancel
              </Button>
            </>
          ) : (
            <>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => setEditing(true)}
                disabled={entry.is_published}
              >
                Edit
              </Button>
              <Button
                size="sm"
                variant="danger"
                onClick={onDelete}
                disabled={entry.is_published || allPublished}
              >
                Delete
              </Button>
            </>
          )}
        </div>
      </Td>
    </tr>
  );
}
