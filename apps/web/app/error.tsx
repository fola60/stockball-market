"use client";

export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main className="grid min-h-screen place-items-center bg-[#080b10] px-5 text-[#edf1f5]">
      <section className="w-full max-w-md rounded-xl border border-[#222a35] bg-[#0e131a] p-7">
        <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#8fb5ff]">Market feed unavailable</p>
        <h1 className="mt-3 text-2xl font-semibold tracking-[-0.03em]">Stockball could not reach the API.</h1>
        <p className="mt-3 text-sm leading-6 text-[#818b97]">Make sure the local API and PostgreSQL services are running, then try the request again.</p>
        <button type="button" onClick={reset} className="mt-6 h-10 rounded-lg bg-[#8fb5ff] px-4 text-xs font-extrabold text-[#080b10] hover:bg-[#a9c6ff] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff] focus-visible:ring-offset-2 focus-visible:ring-offset-[#0e131a]">Try again</button>
      </section>
    </main>
  );
}
