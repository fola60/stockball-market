export default function Loading() {
  return (
    <main className="min-h-screen bg-[#080b10] text-[#edf1f5]">
      <div className="h-[68px] border-b border-[#202630]" />
      <section className="mx-auto w-full max-w-[1120px] px-3 py-9 md:px-7">
        <div className="h-10 w-56 animate-pulse rounded-lg bg-[#161c24] motion-reduce:animate-none" />
        <div className="mt-9 divide-y divide-[#222a35] border-y border-[#222a35]">
          {Array.from({ length: 8 }, (_, index) => <div key={index} className="h-20 animate-pulse bg-[#0e131a]/40 motion-reduce:animate-none" />)}
        </div>
      </section>
    </main>
  );
}
