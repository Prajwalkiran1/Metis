"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function AdminHome() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/admin/academic");
  }, [router]);
  return null;
}
