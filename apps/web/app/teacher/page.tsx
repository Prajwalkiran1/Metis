"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function TeacherHome() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/teacher/attendance");
  }, [router]);
  return null;
}
