"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function ParentRoot() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/parent/marks");
  }, [router]);
  return null;
}
