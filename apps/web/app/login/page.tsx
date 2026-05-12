"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { ApiError, login } from "@/lib/api";
import { Button, Card, ErrorText, Field, Input } from "@/components/ui";

const schema = z.object({
  email: z.string().email("enter a valid email"),
  password: z.string().min(1, "required"),
});
type FormData = z.infer<typeof schema>;

export default function LoginPage() {
  const router = useRouter();
  const [submitError, setSubmitError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormData>({ resolver: zodResolver(schema) });

  const onSubmit = handleSubmit(async (values) => {
    setSubmitError(null);
    try {
      const role = await login(values.email, values.password);
      if (role !== "admin") {
        setSubmitError("only admins can use this console for now");
        return;
      }
      router.replace("/admin/academic");
    } catch (e) {
      const msg =
        e instanceof ApiError ? e.message : "login failed — please retry";
      setSubmitError(msg);
    }
  });

  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm p-6">
        <h1 className="mb-1 text-lg font-semibold text-zinc-900">Sign in</h1>
        <p className="mb-5 text-xs text-zinc-500">
          Metis admin console — use your college credentials.
        </p>
        <form onSubmit={onSubmit} className="space-y-3">
          <Field
            label="Email"
            htmlFor="email"
            error={errors.email?.message}
          >
            <Input
              id="email"
              type="email"
              autoComplete="email"
              {...register("email")}
            />
          </Field>
          <Field
            label="Password"
            htmlFor="password"
            error={errors.password?.message}
          >
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              {...register("password")}
            />
          </Field>
          <ErrorText>{submitError}</ErrorText>
          <Button type="submit" disabled={isSubmitting} className="w-full">
            {isSubmitting ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </Card>
    </main>
  );
}
