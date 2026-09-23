"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { AuthForm, type AuthMode } from "@/app/login/auth-form";

const AUTH_EVENT = "stockball:auth";

export function AuthTrigger({
  mode = "login",
  children,
  className,
}: {
  mode?: AuthMode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <button
      type="button"
      className={className}
      onClick={() => window.dispatchEvent(new CustomEvent(AUTH_EVENT, { detail: mode }))}
    >
      {children}
    </button>
  );
}

export function AuthDialog({ initialMode = null }: { initialMode?: AuthMode | null }) {
  const [mode, setMode] = useState<AuthMode | null>(initialMode);
  const dialog = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function open(event: Event) {
      setMode((event as CustomEvent<AuthMode>).detail ?? "login");
    }
    window.addEventListener(AUTH_EVENT, open);
    return () => window.removeEventListener(AUTH_EVENT, open);
  }, []);

  useEffect(() => {
    if (!mode) return;
    const previous = document.activeElement as HTMLElement | null;
    const frame = requestAnimationFrame(() => {
      dialog.current?.querySelector<HTMLElement>("input")?.focus();
    });
    function handleDialogKeys(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setMode(null);
        return;
      }
      if (event.key !== "Tab" || !dialog.current) return;
      const focusable = Array.from(dialog.current.querySelectorAll<HTMLElement>("button:not([disabled]), input:not([disabled]), a[href]"));
      const first = focusable[0];
      const last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    }
    document.addEventListener("keydown", handleDialogKeys);
    document.body.style.overflow = "hidden";
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("keydown", handleDialogKeys);
      document.body.style.overflow = "";
      previous?.focus();
    };
  }, [mode]);

  if (!mode) return null;

  return (
    <div
      ref={dialog}
      role="dialog"
      aria-modal="true"
      aria-label={mode === "login" ? "Sign in to Stockball" : "Create a Stockball account"}
      className="fixed inset-0 z-50 grid items-end bg-black/75 p-0 sm:place-items-center sm:p-6"
      onMouseDown={(event) => { if (event.target === event.currentTarget) setMode(null); }}
    >
      <div className="relative max-h-[92vh] w-full overflow-y-auto border border-[#2a3441] bg-[#0e131a] px-5 py-7 sm:max-w-[500px] sm:rounded-xl sm:px-8 sm:py-8">
        <button
          type="button"
          aria-label="Close authentication dialog"
          onClick={() => setMode(null)}
          className="absolute right-4 top-4 grid size-9 place-items-center rounded-lg text-[#8d97a3] hover:bg-white/[0.05] hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]"
        >
          <svg viewBox="0 0 20 20" className="size-4" fill="none" aria-hidden="true"><path d="m5 5 10 10M15 5 5 15" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"/></svg>
        </button>
        <AuthForm initialMode={mode} onSuccess={() => setMode(null)} compact />
      </div>
    </div>
  );
}
