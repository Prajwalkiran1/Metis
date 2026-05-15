"use client";

import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import clsx from "clsx";

import { getAccessToken, getRole } from "@/lib/auth";
import { api, logout } from "@/lib/api";
import { RoleBadge } from "@/components/RoleBadge";

type NavEntry = {
  href: string;
  label: string;
  disabled?: boolean;
  releaseGated?: "hall_ticket" | "grade_card";
};

const NAV: NavEntry[] = [
  { href: "/student/dashboard", label: "Dashboard" },
  { href: "/student/registration", label: "Registration" },
  { href: "/student/attendance", label: "Attendance" },
  { href: "/student/marks", label: "Marks" },
  { href: "/student/hall-ticket", label: "Hall ticket", releaseGated: "hall_ticket" },
  { href: "/student/grade-card", label: "Grade card", releaseGated: "grade_card" },
  { href: "/student/re-eval", label: "Re-evaluation" },
  // Stubs for future student-side modules.
  { href: "/student/materials", label: "Materials", disabled: true },
];

export default function StudentLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [ready, setReady] = useState(false);
  const [hasHallTicket, setHasHallTicket] = useState<boolean | null>(null);
  const [hasGradeCard, setHasGradeCard] = useState<boolean | null>(null);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    if (getRole() !== "student") {
      router.replace("/login");
      return;
    }
    setReady(true);
  }, [router]);

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    (async () => {
      try {
        const ticket = await api<unknown | null>("/workflow/hall-tickets/me");
        if (!cancelled) setHasHallTicket(ticket !== null);
      } catch {
        if (!cancelled) setHasHallTicket(false);
      }
      try {
        const cards = await api<unknown[]>("/workflow/grade-cards");
        if (!cancelled) setHasGradeCard(Array.isArray(cards) && cards.length > 0);
      } catch {
        if (!cancelled) setHasGradeCard(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ready]);

  if (!ready) {
    return <p className="p-8 text-sm text-zinc-500">Loading…</p>;
  }

  const isNavVisible = (n: NavEntry) => {
    if (!n.releaseGated) return true;
    // While the check is in flight, keep the entry visible so the user
    // doesn't see a flash-hide. Only hide once we know it's empty.
    if (n.releaseGated === "hall_ticket") return hasHallTicket !== false;
    if (n.releaseGated === "grade_card") return hasGradeCard !== false;
    return true;
  };

  return (
    <div className="flex min-h-screen">
      <aside className="w-56 border-r border-zinc-200 bg-white p-3">
        <div className="mb-5 px-2">
          <div className="text-sm font-semibold text-zinc-900">Metis</div>
          <RoleBadge routeContext="student" />
        </div>
        <nav className="space-y-1">
          {NAV.filter(isNavVisible).map((n) => (
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
