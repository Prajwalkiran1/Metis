"use client";

import { useEffect, useMemo, useRef, useState } from "react";
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

type Role = "admin" | "hod" | "teacher" | "student" | "parent";
type UserStatus = "invited" | "active" | "suspended" | "deleted";

type UserRow = {
  id: string;
  email: string;
  name: string;
  role: Role;
  status: UserStatus;
  usn: string | null;
  hod_of_department_id: string | null;
  phone: string | null;
  created_at: string;
};

type UserListResponse = { items: UserRow[]; total: number };

type Department = { id: string; code: string; name: string };

const ROLE_OPTIONS = ["admin", "hod", "teacher", "student", "parent"] as const;
const STATUS_OPTIONS = [
  "invited",
  "active",
  "suspended",
  "deleted",
] as const;

const PAGE_SIZE = 50;

function statusTone(s: UserStatus): "neutral" | "green" | "amber" | "red" {
  if (s === "active") return "green";
  if (s === "invited") return "amber";
  if (s === "suspended" || s === "deleted") return "red";
  return "neutral";
}

// ─── Role change dialog form schema ────────────────────────────────────────
const roleChangeSchema = z
  .object({
    role: z.enum(ROLE_OPTIONS),
    hod_of_department_id: z.string().optional(),
  })
  .refine((d) => d.role !== "hod" || !!d.hod_of_department_id, {
    message: "department is required when role is HOD",
    path: ["hod_of_department_id"],
  });

type RoleChangeForm = z.infer<typeof roleChangeSchema>;

// ─── Page ──────────────────────────────────────────────────────────────────
export default function UsersPage() {
  const [items, setItems] = useState<UserRow[] | null>(null);
  const [total, setTotal] = useState(0);
  const [filterRole, setFilterRole] = useState<Role | "">("");
  const [filterStatus, setFilterStatus] = useState<UserStatus | "">("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [csvOpen, setCsvOpen] = useState(false);
  const [roleDialogFor, setRoleDialogFor] = useState<UserRow | null>(null);
  const [departments, setDepartments] = useState<Department[]>([]);

  async function load() {
    setErr(null);
    try {
      const data = await api<UserListResponse>("/users", {
        query: {
          role: filterRole || undefined,
          status_filter: filterStatus || undefined,
          q: q.trim() || undefined,
          limit: PAGE_SIZE,
          offset,
        },
      });
      setItems(data.items);
      setTotal(data.total);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "load failed");
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterRole, filterStatus, offset]);

  useEffect(() => {
    // Departments are needed for HOD role assignment; load once.
    (async () => {
      try {
        const d = await api<{ items: Department[]; total: number }>(
          "/departments",
          { query: { limit: 200 } },
        );
        setDepartments(d.items);
      } catch {
        /* departments are best-effort; if it fails, HOD assignment shows raw UUIDs */
      }
    })();
  }, []);

  const deptById = useMemo(() => {
    const m: Record<string, Department> = {};
    departments.forEach((d) => (m[d.id] = d));
    return m;
  }, [departments]);

  async function toggleStatus(u: UserRow) {
    const next: UserStatus = u.status === "active" ? "suspended" : "active";
    const verb = next === "active" ? "Activate" : "Suspend";
    if (!confirm(`${verb} ${u.email}?`)) return;
    try {
      await api(`/users/${u.id}/status`, {
        method: "PATCH",
        body: { status: next },
      });
      await load();
    } catch (e) {
      alert(e instanceof ApiError ? e.message : "update failed");
    }
  }

  function onSearch(e: React.FormEvent) {
    e.preventDefault();
    setOffset(0);
    load();
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-zinc-900">Users</h1>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => setCsvOpen(true)}>
            Bulk CSV import
          </Button>
        </div>
      </div>

      {/* Filters */}
      <Card className="p-3">
        <form
          onSubmit={onSearch}
          className="flex flex-wrap items-end gap-3"
        >
          <div className="w-40">
            <Field label="Role">
              <Select
                value={filterRole}
                onChange={(e) => {
                  setOffset(0);
                  setFilterRole(e.target.value as Role | "");
                }}
              >
                <option value="">All</option>
                {ROLE_OPTIONS.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <div className="w-40">
            <Field label="Status">
              <Select
                value={filterStatus}
                onChange={(e) => {
                  setOffset(0);
                  setFilterStatus(e.target.value as UserStatus | "");
                }}
              >
                <option value="">All</option>
                {STATUS_OPTIONS.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <div className="w-80 flex-1">
            <Field label="Search (email / name / USN)">
              <Input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="e.g. 1BM23CS or @bmsce"
              />
            </Field>
          </div>
          <Button type="submit">Apply</Button>
        </form>
      </Card>

      <ErrorText>{err}</ErrorText>

      {items === null ? (
        <Loading />
      ) : items.length === 0 ? (
        <p className="text-sm text-zinc-500">No users match these filters.</p>
      ) : (
        <Card className="overflow-x-auto">
          <Table>
            <thead>
              <tr>
                <Th>Name</Th>
                <Th>Email</Th>
                <Th>USN</Th>
                <Th>Role</Th>
                <Th>Dept (HOD)</Th>
                <Th>Status</Th>
                <Th className="text-right">Actions</Th>
              </tr>
            </thead>
            <tbody>
              {items.map((u) => {
                const dept =
                  u.hod_of_department_id && deptById[u.hod_of_department_id];
                return (
                  <tr key={u.id}>
                    <Td>{u.name}</Td>
                    <Td className="text-zinc-600">{u.email}</Td>
                    <Td>
                      {u.usn ? (
                        <code className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs">
                          {u.usn}
                        </code>
                      ) : (
                        <span className="text-zinc-400">—</span>
                      )}
                    </Td>
                    <Td>
                      <Badge>{u.role}</Badge>
                    </Td>
                    <Td className="text-zinc-600">
                      {dept ? `${dept.code} (${dept.name})` : u.hod_of_department_id ?? "—"}
                    </Td>
                    <Td>
                      <Badge tone={statusTone(u.status)}>{u.status}</Badge>
                    </Td>
                    <Td className="text-right">
                      <div className="flex justify-end gap-2">
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => setRoleDialogFor(u)}
                        >
                          Change role
                        </Button>
                        <Button
                          size="sm"
                          variant={u.status === "active" ? "danger" : "primary"}
                          onClick={() => toggleStatus(u)}
                        >
                          {u.status === "active" ? "Suspend" : "Activate"}
                        </Button>
                      </div>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        </Card>
      )}

      {/* Pagination */}
      <div className="flex items-center justify-between text-xs text-zinc-500">
        <span>
          {items === null
            ? ""
            : `Showing ${offset + 1}–${offset + items.length} of ${total}`}
        </span>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="secondary"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          >
            Prev
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={items === null || offset + PAGE_SIZE >= total}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            Next
          </Button>
        </div>
      </div>

      {/* Role change dialog */}
      {roleDialogFor && (
        <RoleChangeDialog
          user={roleDialogFor}
          departments={departments}
          onClose={() => setRoleDialogFor(null)}
          onSaved={async () => {
            setRoleDialogFor(null);
            await load();
          }}
        />
      )}

      {/* Bulk CSV dialog */}
      {csvOpen && (
        <BulkCsvDialog
          onClose={() => setCsvOpen(false)}
          onCommitted={async () => {
            setCsvOpen(false);
            await load();
          }}
        />
      )}
    </div>
  );
}

// ─── Role change dialog ────────────────────────────────────────────────────
function RoleChangeDialog({
  user,
  departments,
  onClose,
  onSaved,
}: {
  user: UserRow;
  departments: Department[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<RoleChangeForm>({
    resolver: zodResolver(roleChangeSchema),
    defaultValues: {
      role: user.role,
      hod_of_department_id: user.hod_of_department_id ?? "",
    },
  });
  const [serverErr, setServerErr] = useState<string | null>(null);
  const role = watch("role");

  const onSubmit = handleSubmit(async (values) => {
    setServerErr(null);
    try {
      await api(`/users/${user.id}/role`, {
        method: "PATCH",
        body: {
          role: values.role,
          hod_of_department_id:
            values.role === "hod" ? values.hod_of_department_id : null,
        },
      });
      onSaved();
    } catch (e) {
      setServerErr(e instanceof ApiError ? e.message : "update failed");
    }
  });

  return (
    <Dialog
      open
      onClose={onClose}
      title={`Change role — ${user.email}`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="role-form" disabled={isSubmitting}>
            {isSubmitting ? "Saving…" : "Save"}
          </Button>
        </>
      }
    >
      <form id="role-form" onSubmit={onSubmit} className="space-y-3">
        <Field label="Role" error={errors.role?.message}>
          <Select {...register("role")}>
            {ROLE_OPTIONS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </Select>
        </Field>
        {role === "hod" && (
          <Field
            label="Department"
            error={errors.hod_of_department_id?.message}
          >
            <Select {...register("hod_of_department_id")}>
              <option value="">—</option>
              {departments.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.code} · {d.name}
                </option>
              ))}
            </Select>
          </Field>
        )}
        <ErrorText>{serverErr}</ErrorText>
      </form>
    </Dialog>
  );
}

// ─── Bulk CSV dialog ───────────────────────────────────────────────────────
type BulkCsvResponse = {
  dry_run: boolean;
  total_rows: number;
  valid_rows: number;
  inserted: number;
  skipped_existing: number;
  errors: {
    row_number: number;
    code: string;
    message: string;
    email: string | null;
  }[];
};

function BulkCsvDialog({
  onClose,
  onCommitted,
}: {
  onClose: () => void;
  onCommitted: () => void;
}) {
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [result, setResult] = useState<BulkCsvResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function send(dryRun: boolean) {
    setErr(null);
    const file = fileRef.current?.files?.[0];
    if (!file) {
      setErr("pick a CSV file first");
      return;
    }
    const fd = new FormData();
    fd.append("file", file);
    fd.append("dry_run", String(dryRun));
    setBusy(true);
    try {
      const data = await api<BulkCsvResponse>("/users/bulk-csv", {
        method: "POST",
        body: fd,
      });
      setResult(data);
      if (!dryRun) onCommitted();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "upload failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title="Bulk CSV import"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Close
          </Button>
          <Button
            variant="secondary"
            onClick={() => send(true)}
            disabled={busy}
          >
            {busy ? "Validating…" : "Dry run"}
          </Button>
          <Button
            onClick={() => send(false)}
            disabled={busy || !result || result.errors.length > 0}
          >
            {busy ? "Importing…" : "Commit"}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <p className="text-xs text-zinc-600">
          Headers (required): <code>email,name,role,usn,phone</code>. USN is
          required for students and must match <code>1BM&lt;YY&gt;&lt;DD&gt;&lt;RRR&gt;</code>.
          Run a dry run first; the Commit button enables only when the dry run
          finds zero errors.
        </p>
        <Field label="CSV file">
          <input
            ref={fileRef}
            type="file"
            accept=".csv,text/csv"
            className="text-sm"
          />
        </Field>
        <ErrorText>{err}</ErrorText>
        {result && (
          <div className="rounded border border-zinc-200 p-3 text-sm">
            <p>
              Mode:{" "}
              <strong>{result.dry_run ? "dry run" : "committed"}</strong> ·
              Total rows: {result.total_rows} · Valid: {result.valid_rows} ·
              Inserted: {result.inserted} · Skipped (already in college):{" "}
              {result.skipped_existing} · Errors: {result.errors.length}
            </p>
            {result.errors.length > 0 && (
              <details className="mt-2">
                <summary className="cursor-pointer text-xs text-red-700">
                  Show {result.errors.length} error{result.errors.length === 1 ? "" : "s"}
                </summary>
                <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-zinc-700">
                  {result.errors.slice(0, 50).map((e) => (
                    <li key={`${e.row_number}-${e.code}`}>
                      Row {e.row_number} ({e.email ?? "—"}): {e.code} — {e.message}
                    </li>
                  ))}
                  {result.errors.length > 50 && (
                    <li className="text-zinc-500">…and more.</li>
                  )}
                </ul>
              </details>
            )}
          </div>
        )}
      </div>
    </Dialog>
  );
}
