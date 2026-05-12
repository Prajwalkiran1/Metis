"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getAccessToken } from "@/lib/auth";

export default function HomePage() {
  const router = useRouter();
  useEffect(() => {
    router.replace(getAccessToken() ? "/admin/academic" : "/login");
  }, [router]);
  return <p className="p-8 text-zinc-500">Loading…</p>;
}
