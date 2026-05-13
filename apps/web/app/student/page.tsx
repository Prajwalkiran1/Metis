"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function StudentHome() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/student/attendance");
  }, [router]);
  return null;
}
