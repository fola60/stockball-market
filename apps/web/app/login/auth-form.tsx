"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

export type AuthMode = "login" | "register";

export function AuthForm({ initialMode = "login", onSuccess, compact = false }: { initialMode?: AuthMode; onSuccess?: () => void; compact?: boolean }) {
  const router = useRouter();
  const [mode, setMode] = useState<AuthMode>(initialMode);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const form = new FormData(event.currentTarget);
    const payload = Object.fromEntries(form.entries());
    try {
      const response = await fetch(`/api/auth/${mode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await response.json();
      if (!response.ok) {
        setError(body.message ?? body.detail?.[0]?.msg ?? "Unable to sign in.");
        return;
      }
      onSuccess?.();
      if (!compact) router.push("/");
      router.refresh();
    } catch {
      setError("Stockball could not be reached. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  function changeMode(next: AuthMode) {
    setMode(next);
    setError("");
  }

  return (
    <div className={compact ? "w-full" : "w-full max-w-[460px]"}>
      <div className="mb-8 flex items-end justify-between gap-6">
        <div>
          <h1 className="text-[30px] font-semibold tracking-[-0.03em] text-white">
            {mode === "login" ? "Return to the market" : "Enter the market"}
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-[#8d97a3]">
            {mode === "login"
              ? "Sign in to trade player shares and manage your virtual portfolio."
              : "Create an account with £100,000 in virtual buying power."}
          </p>
        </div>
      </div>

      <div className="mb-6 grid grid-cols-2 rounded-lg border border-[#242c37] bg-[#0b0f15] p-1">
        {(["login", "register"] as const).map((item) => (
          <button
            key={item}
            type="button"
            aria-pressed={mode === item}
            onClick={() => changeMode(item)}
            className={`h-10 rounded-md text-xs font-bold focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff] ${mode === item ? "bg-[#8fb5ff] text-[#080b10]" : "text-[#8d97a3] hover:text-white"}`}
          >
            {item === "login" ? "Sign in" : "Create account"}
          </button>
        ))}
      </div>

      <form onSubmit={submit} className="space-y-4" noValidate>
        {mode === "register" && (
          <>
            <Field label="Name" name="display_name" autoComplete="name" maxLength={128} required />
          </>
        )}
        <Field label="Email" name="email" type="email" autoComplete="email" maxLength={320} required />
        <Field label="Password" name="password" type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} minLength={mode === "register" ? 12 : 1} maxLength={128} required hint={mode === "register" ? "Use at least 12 characters." : undefined} />

        {error && (
          <div role="alert" className="rounded-lg border border-[#f16d73]/35 bg-[#f16d73]/[0.08] px-4 py-3 text-xs leading-relaxed text-[#ff9ca1]">
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={busy}
          className="flex h-12 w-full items-center justify-center rounded-lg bg-[#8fb5ff] px-5 text-xs font-extrabold text-[#080b10] hover:bg-[#a9c6ff] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff] focus-visible:ring-offset-2 focus-visible:ring-offset-[#080b10] disabled:cursor-not-allowed disabled:bg-[#46566e] disabled:text-[#aab4c1]"
        >
          {busy ? "Working…" : mode === "login" ? "Sign in to Stockball" : "Create my portfolio"}
        </button>
      </form>

      <p className="mt-6 text-center text-xs leading-relaxed text-[#687380]">
        Stockball uses virtual cash only. Player-share prices move through simulated buying and selling.
      </p>
    </div>
  );
}

function Field({ label, hint, ...props }: React.InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string }) {
  const hintId = hint ? `${props.name}-hint` : undefined;
  return (
    <label className="block text-xs font-semibold text-[#aab3bd]">
      <span className="mb-2 block">{label}</span>
      <input
        {...props}
        aria-describedby={hintId}
        className="h-12 w-full rounded-lg border border-[#2a3441] bg-[#0e131a] px-3 text-base text-white outline-none placeholder:text-[#5f6975] focus:border-[#8fb5ff] focus:ring-2 focus:ring-[#8fb5ff]/25"
      />
      {hint && <small id={hintId} className="mt-2 block text-[11px] font-medium text-[#687380]">{hint}</small>}
    </label>
  );
}
