"use client";

import { useEffect, useMemo, useState } from "react";

import { ApiError, api } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  ErrorText,
  Loading,
  Select,
  Table,
  Td,
  Th,
} from "@/components/ui";

type Notification = {
  id: string;
  college_id: string;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
  read_at: string | null;
};

type Page = { items: Notification[]; total: number };

type SortDir = "newest" | "oldest";

type Department = { id: string; code: string; name: string };

const PAGE_SIZE = 50;

export default function AdminNotificationsPage() {
  const [items, setItems] = useState<Notification[] | null>(null);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>("newest");
  const [departments, setDepartments] = useState<Department[]>([]);
  const [filterDept, setFilterDept] = useState<string>("");
  const [filterEvent, setFilterEvent] = useState<string>("");

  useEffect(() => {
    (async () => {
      try {
        const r = await api<{ items: Department[]; total: number }>(
          "/departments",
          { query: { limit: 200 } },
        );
        setDepartments(r.items);
      } catch {
        // departments are optional filter context
      }
    })();
  }, []);

  async function reload() {
    try {
      // Backend returns newest-first; we sort client-side when "oldest" is picked.
      const r = await api<Page>("/admin/notifications", {
        query: { limit: PAGE_SIZE, offset },
      });
      setItems(r.items);
      setTotal(r.total);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "load failed");
    }
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offset]);

  const visible = useMemo(() => {
    let arr = items ?? [];
    if (filterDept) {
      arr = arr.filter(
        (n) => (n.payload as { department_id?: string }).department_id === filterDept,
      );
    }
    if (filterEvent) {
      arr = arr.filter((n) => n.event_type === filterEvent);
    }
    return sortDir === "newest"
      ? arr
      : [...arr].sort(
          (a, b) =>
            new Date(a.created_at).getTime() -
            new Date(b.created_at).getTime(),
        );
  }, [items, sortDir, filterDept, filterEvent]);

  const eventTypes = useMemo(() => {
    return Array.from(new Set((items ?? []).map((n) => n.event_type))).sort();
  }, [items]);

  if (err) return <ErrorText>{err}</ErrorText>;
  if (items === null) return <Loading />;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-zinc-900">Notifications</h1>
        <p className="text-sm text-zinc-500">
          Informational feed of department-level events. HOD publish events
          appear here as soon as the HOD signs off — no action required.
        </p>
      </div>

      <Card className="p-3">
        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1">
            <label className="block text-xs font-medium text-zinc-700">
              Sort
            </label>
            <Select
              value={sortDir}
              onChange={(e) => setSortDir(e.target.value as SortDir)}
            >
              <option value="newest">Newest first</option>
              <option value="oldest">Oldest first</option>
            </Select>
          </div>
          <div className="space-y-1">
            <label className="block text-xs font-medium text-zinc-700">
              Event type
            </label>
            <Select
              value={filterEvent}
              onChange={(e) => setFilterEvent(e.target.value)}
            >
              <option value="">all</option>
              {eventTypes.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1">
            <label className="block text-xs font-medium text-zinc-700">
              Department
            </label>
            <Select
              value={filterDept}
              onChange={(e) => setFilterDept(e.target.value)}
            >
              <option value="">all</option>
              {departments.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.code} — {d.name}
                </option>
              ))}
            </Select>
          </div>
          <div className="ml-auto text-xs text-zinc-500">
            {total} total · showing {visible.length}
          </div>
        </div>
      </Card>

      <Card className="overflow-x-auto">
        {visible.length === 0 ? (
          <p className="px-4 py-6 text-sm text-zinc-500">
            No notifications match the current filters.
          </p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>When</Th>
                <Th>Event</Th>
                <Th>Department</Th>
                <Th>Detail</Th>
              </tr>
            </thead>
            <tbody>
              {visible.map((n) => {
                const p = n.payload as {
                  department_id?: string;
                  academic_term_id?: string;
                  semester_setup_id?: string;
                  published_by_user_id?: string;
                };
                const dept = departments.find((d) => d.id === p.department_id);
                return (
                  <tr key={n.id}>
                    <Td className="whitespace-nowrap text-zinc-700">
                      {new Date(n.created_at).toLocaleString()}
                    </Td>
                    <Td>
                      <Badge tone="green">{n.event_type}</Badge>
                    </Td>
                    <Td>{dept ? `${dept.code}` : p.department_id ?? "—"}</Td>
                    <Td>
                      <details>
                        <summary className="cursor-pointer text-xs text-zinc-700">
                          payload
                        </summary>
                        <pre className="mt-2 max-w-md overflow-x-auto whitespace-pre-wrap rounded bg-zinc-50 p-2 text-xs text-zinc-700">
                          {JSON.stringify(n.payload, null, 2)}
                        </pre>
                      </details>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}
      </Card>

      <div className="flex items-center gap-2">
        <Button
          variant="secondary"
          size="sm"
          onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          disabled={offset === 0}
        >
          Previous
        </Button>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => setOffset(offset + PAGE_SIZE)}
          disabled={offset + PAGE_SIZE >= total}
        >
          Next
        </Button>
        <span className="text-xs text-zinc-500">
          {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
        </span>
      </div>
    </div>
  );
}
