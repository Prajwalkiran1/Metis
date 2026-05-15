"use client";

import { useEffect, useState } from "react";

import { Badge } from "@/components/ui";
import { getRole, type Role } from "@/lib/auth";

const ROLE_LABELS: Record<Role, string> = {
  admin: "admin",
  hod: "HOD",
  teacher: "teacher",
  student: "student",
  parent: "parent",
};

const ROUTE_LABELS: Record<Role, string> = {
  admin: "admin panel",
  hod: "HOD panel",
  teacher: "teacher panel",
  student: "student panel",
  parent: "parent panel",
};

export function RoleBadge({ routeContext }: { routeContext: Role }) {
  const [actual, setActual] = useState<Role | null>(null);

  useEffect(() => {
    setActual(getRole());
  }, []);

  if (actual === null) return null;
  if (actual === routeContext) {
    return (
      <span className="text-xs text-zinc-500">
        {ROLE_LABELS[actual]}
      </span>
    );
  }

  return (
    <div className="mt-1">
      <Badge tone="amber">
        Logged in as {ROLE_LABELS[actual]} · viewing {ROUTE_LABELS[routeContext]}
      </Badge>
    </div>
  );
}
