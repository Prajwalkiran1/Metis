"use client";

/**
 * Minimal UI primitives — shadcn/ui look without the full install ceremony.
 * Plain Tailwind, accessible defaults, no decorative styling. Components are
 * intentionally simple so the redesign phase can swap them out painlessly.
 */
import {
  forwardRef,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type LabelHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TableHTMLAttributes,
  type TdHTMLAttributes,
  type ThHTMLAttributes,
} from "react";
import clsx from "clsx";

export function Button({
  className,
  variant = "primary",
  size = "md",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger" | "ghost";
  size?: "sm" | "md";
}) {
  const variants = {
    primary:
      "bg-zinc-900 text-white hover:bg-zinc-800 disabled:bg-zinc-400",
    secondary:
      "bg-white border border-zinc-300 text-zinc-900 hover:bg-zinc-50",
    danger: "bg-red-600 text-white hover:bg-red-700 disabled:bg-red-300",
    ghost: "bg-transparent text-zinc-700 hover:bg-zinc-100",
  } as const;
  const sizes = { sm: "text-xs px-2 py-1", md: "text-sm px-3 py-1.5" };
  return (
    <button
      {...rest}
      className={clsx(
        "inline-flex items-center justify-center rounded font-medium disabled:cursor-not-allowed",
        variants[variant],
        sizes[size],
        className,
      )}
    />
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...rest }, ref) {
    return (
      <input
        ref={ref}
        {...rest}
        className={clsx(
          "w-full rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm",
          "focus:outline-none focus:ring-1 focus:ring-zinc-900",
          "disabled:bg-zinc-100",
          className,
        )}
      />
    );
  },
);

export function Label({
  className,
  ...rest
}: LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label
      {...rest}
      className={clsx("block text-xs font-medium text-zinc-700", className)}
    />
  );
}

export const Select = forwardRef<
  HTMLSelectElement,
  SelectHTMLAttributes<HTMLSelectElement>
>(function Select({ className, children, ...rest }, ref) {
  return (
    <select
      ref={ref}
      {...rest}
      className={clsx(
        "w-full rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm",
        "focus:outline-none focus:ring-1 focus:ring-zinc-900",
        className,
      )}
    >
      {children}
    </select>
  );
});

export function Field({
  label,
  htmlFor,
  error,
  children,
}: {
  label: string;
  htmlFor?: string;
  error?: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-1">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {error ? <p className="text-xs text-red-600">{error}</p> : null}
    </div>
  );
}

export function Card({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={clsx(
        "rounded border border-zinc-200 bg-white shadow-sm",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function Table(props: TableHTMLAttributes<HTMLTableElement>) {
  return (
    <table
      {...props}
      className={clsx("w-full text-sm", props.className)}
    />
  );
}

export function Th(props: ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      {...props}
      className={clsx(
        "border-b border-zinc-200 bg-zinc-50 px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-zinc-600",
        props.className,
      )}
    />
  );
}

export function Td(props: TdHTMLAttributes<HTMLTableCellElement>) {
  return (
    <td
      {...props}
      className={clsx(
        "border-b border-zinc-100 px-3 py-2 align-middle",
        props.className,
      )}
    />
  );
}

export function Badge({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "green" | "amber" | "red";
  children: ReactNode;
}) {
  const tones = {
    neutral: "bg-zinc-100 text-zinc-700",
    green: "bg-green-100 text-green-700",
    amber: "bg-amber-100 text-amber-800",
    red: "bg-red-100 text-red-700",
  } as const;
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded px-2 py-0.5 text-xs font-medium",
        tones[tone],
      )}
    >
      {children}
    </span>
  );
}

export function Dialog({
  open,
  onClose,
  title,
  children,
  footer,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/40 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded bg-white p-5 shadow-lg"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-semibold text-zinc-900">{title}</h2>
          <button
            type="button"
            className="text-zinc-500 hover:text-zinc-900"
            onClick={onClose}
            aria-label="Close"
          >
            ×
          </button>
        </div>
        <div className="space-y-3">{children}</div>
        {footer ? (
          <div className="mt-5 flex items-center justify-end gap-2">
            {footer}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function Tabs({
  tabs,
  active,
  onChange,
}: {
  tabs: { id: string; label: string }[];
  active: string;
  onChange: (id: string) => void;
}) {
  return (
    <div className="border-b border-zinc-200">
      <nav className="flex gap-1">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => onChange(t.id)}
            className={clsx(
              "px-3 py-2 text-sm font-medium",
              t.id === active
                ? "border-b-2 border-zinc-900 text-zinc-900"
                : "text-zinc-500 hover:text-zinc-900",
            )}
          >
            {t.label}
          </button>
        ))}
      </nav>
    </div>
  );
}

export function ErrorText({ children }: { children: ReactNode }) {
  if (!children) return null;
  return <p className="text-sm text-red-600">{children}</p>;
}

export function Loading() {
  return <p className="text-sm text-zinc-500">Loading…</p>;
}
