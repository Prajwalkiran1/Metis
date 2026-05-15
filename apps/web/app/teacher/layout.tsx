"use client";

import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import clsx from "clsx";

import { getAccessToken, getRole } from "@/lib/auth";
import { logout } from "@/lib/api";

const NAV = [
  { href: "/teacher/attendance", label: "Attendance" },
  { href: "/teacher/marks", label: "Marks" },
  { href: "/teacher/tasks", label: "Tasks" },
  // Stubs for future teacher-side modules.
  { href: "/teacher/materials", label: "Materials", disabled: true },
];

export default function TeacherLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    const role = getRole();
    // HODs follow links here from /hod/electives to configure schemes on
    // offerings they don't necessarily teach. Admins see the same panels
    // read-only.
    if (role !== "teacher" && role !== "admin" && role !== "hod") {
      router.replace("/login");
      return;
    }
    setReady(true);
  }, [router]);

  if (!ready) {
    return <p className="p-8 text-sm text-zinc-500">Loading…</p>;
  }

  return (
    <div className="flex min-h-screen">
      <aside className="w-56 border-r border-zinc-200 bg-white p-3">
        <div className="mb-5 px-2 text-sm font-semibold text-zinc-900">
          Metis · teacher
        </div>
        <nav className="space-y-1">
          {NAV.map((n) => (
            <Link
              key={n.href}
              href={n.disabled ? "#" : n.href}
              aria-disabled={n.disabled}
              className={clsx(
                "block rounded px-2 py-1.5 text-sm",
                n.disabled
                  ? "cursor-not-allowed text-zinc-400"
                  : pathname.startsWith(n.href)
                    ? "bg-zinc-100 font-medium text-zinc-900"
                    : "text-zinc-700 hover:bg-zinc-100",
              )}
              onClick={(e) => n.disabled && e.preventDefault()}
            >
              {n.label}
            </Link>
          ))}
        </nav>
        <button
          type="button"
          className="mt-6 w-full rounded px-2 py-1.5 text-left text-sm text-zinc-600 hover:bg-zinc-100"
          onClick={async () => {
            await logout();
            router.replace("/login");
          }}
        >
          Sign out
        </button>
      </aside>
      <main className="flex-1 overflow-auto p-6">{children}</main>
    </div>
  );
}
