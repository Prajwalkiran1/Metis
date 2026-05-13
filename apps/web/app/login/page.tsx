"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import {
  ApiError,
  fetchGoogleConfig,
  login,
  loginWithGoogle,
} from "@/lib/api";
import type { Role } from "@/lib/auth";
import { Button, Card, ErrorText, Field, Input } from "@/components/ui";

const schema = z.object({
  email: z.string().email("enter a valid email"),
  password: z.string().min(1, "required"),
});
type FormData = z.infer<typeof schema>;

function landingFor(role: Role): string {
  if (role === "admin") return "/admin/academic";
  if (role === "teacher") return "/teacher/attendance";
  if (role === "parent") return "/parent/marks";
  return "/student/attendance";
}

declare global {
  interface Window {
    google?: {
      accounts?: {
        id?: {
          initialize: (config: {
            client_id: string;
            callback: (response: { credential: string }) => void;
            auto_select?: boolean;
          }) => void;
          renderButton: (
            parent: HTMLElement,
            options: Record<string, unknown>,
          ) => void;
        };
      };
    };
  }
}

export default function LoginPage() {
  const router = useRouter();
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [googleClientId, setGoogleClientId] = useState<string | null>(null);
  const googleBtnRef = useRef<HTMLDivElement | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormData>({ resolver: zodResolver(schema) });

  // Ask the API once whether Google sign-in is enabled, and with which
  // client ID. Frontend env can also set NEXT_PUBLIC_GOOGLE_CLIENT_ID
  // for a faster first paint; the API value wins if they disagree.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const cfg = await fetchGoogleConfig();
        if (cancelled) return;
        if (cfg.enabled && cfg.client_id) {
          setGoogleClientId(cfg.client_id);
        } else if (process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID) {
          setGoogleClientId(process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID);
        }
      } catch {
        // Backend unreachable — fall back to env var if present.
        if (process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID) {
          setGoogleClientId(process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Inject the Google Identity Services script + render the button.
  useEffect(() => {
    if (!googleClientId) return;

    function init() {
      const g = window.google?.accounts?.id;
      if (!g || !googleBtnRef.current) return;
      g.initialize({
        client_id: googleClientId!,
        callback: async (response) => {
          setSubmitError(null);
          try {
            const role = await loginWithGoogle(response.credential);
            router.replace(landingFor(role));
            return;
          } catch (e) {
            const msg =
              e instanceof ApiError
                ? e.message
                : "google sign-in failed — please retry";
            setSubmitError(msg);
          }
        },
      });
      g.renderButton(googleBtnRef.current, {
        type: "standard",
        theme: "outline",
        size: "large",
        text: "signin_with",
        width: 280,
      });
    }

    if (window.google?.accounts?.id) {
      init();
      return;
    }

    const existing = document.getElementById("gis-script");
    if (existing) {
      existing.addEventListener("load", init);
      return () => existing.removeEventListener("load", init);
    }

    const s = document.createElement("script");
    s.id = "gis-script";
    s.src = "https://accounts.google.com/gsi/client";
    s.async = true;
    s.defer = true;
    s.onload = init;
    document.head.appendChild(s);
  }, [googleClientId, router]);

  const onSubmit = handleSubmit(async (values) => {
    setSubmitError(null);
    try {
      const role = await login(values.email, values.password);
      router.replace(landingFor(role));
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

        {googleClientId && (
          <div className="mb-5">
            <div ref={googleBtnRef} className="flex justify-center" />
            <div className="my-4 flex items-center gap-3 text-xs text-zinc-400">
              <div className="h-px flex-1 bg-zinc-200" />
              <span>or</span>
              <div className="h-px flex-1 bg-zinc-200" />
            </div>
          </div>
        )}

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
