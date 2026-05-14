"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function HodHome() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/hod/dashboard");
  }, [router]);
  return null;
}
