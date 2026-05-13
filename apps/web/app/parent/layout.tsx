"use client";

import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import clsx from "clsx";

import { getAccessToken, getRole } from "@/lib/auth";
import { logout } from "@/lib/api";

const NAV = [{ href: "/parent/marks", label: "Marks" }];

export default function ParentLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    if (getRole() !== "parent") {
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
          Metis · parent
        </div>
        <nav className="space-y-1">
          {NAV.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              className={clsx(
                "block rounded px-2 py-1.5 text-sm",
                pathname.startsWith(n.href)
                  ? "bg-zinc-100 font-medium text-zinc-900"
                  : "text-zinc-700 hover:bg-zinc-100",
              )}
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
