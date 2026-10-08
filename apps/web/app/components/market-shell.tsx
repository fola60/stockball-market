import type { ReactNode } from "react";
import Link from "next/link";
import type { Account, Instrument, TickerStock } from "@/lib/api";
import { formatCurrency, formatPercent, initials } from "@/lib/format";
import { PlayerSearch } from "./player-search";
import { AuthDialog, AuthTrigger } from "./auth-dialog";
import type { AuthMode } from "@/app/login/auth-form";

export type ShellSection = "market" | "players" | "portfolio" | "leaderboard";

export function Label({ children }: { children: ReactNode }) {
  return <p className="mb-2 text-[11px] font-semibold leading-none text-[#77818e]">{children}</p>;
}

function Header({ active, account, tickerStocks, searchInstruments }: { active: ShellSection; account: Account | null; tickerStocks: TickerStock[]; searchInstruments: Instrument[] }) {
  return <>
    <header className="sticky top-0 z-20 flex h-[68px] items-center border-b border-[#202630] bg-[#080b10]/95 px-4 backdrop-blur-xl md:px-7">
      <Link href="/" aria-label="Stockball home" className="flex items-center gap-2.5 text-lg font-extrabold tracking-[-0.025em]">
        <span className="flex h-7 items-end gap-[2px] -skew-x-6" aria-hidden="true"><i className="h-2 w-1 rounded-sm bg-[#8fb5ff]"/><i className="h-3.5 w-1 rounded-sm bg-[#8fb5ff]"/><i className="h-5 w-1 rounded-sm bg-[#8fb5ff]"/><i className="h-7 w-1 rounded-sm bg-[#8fb5ff]"/></span>
        <span>STOCK<span className="text-[#8fb5ff]">BALL</span></span>
      </Link>
      <nav aria-label="Primary" className="ml-5 hidden items-center gap-1 sm:flex md:ml-8">
        {([["/", "Market", "market"], ["/players", "Players", "players"], ["/leaderboard", "Leaderboard", "leaderboard"]] as const).map(([href, label, section]) => (
          <Link key={href} href={href} aria-current={active === section ? "page" : undefined} className={`h-9 rounded-lg px-3 text-xs font-bold leading-9 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff] ${active === section ? "bg-white/[0.05] text-white" : "text-[#7c8693] hover:bg-white/[0.03] hover:text-white"}`}>{label}</Link>
        ))}
      </nav>
      <div className="ml-auto flex items-center gap-2">
        <Link href="/leaderboard" aria-label="Leaderboard" className="grid size-9 place-items-center rounded-lg border border-[#252d38] text-[#aab4c1] hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff] sm:hidden"><NavIcon kind="leaderboard" /></Link>
        <PlayerSearch instruments={searchInstruments}/>
        {account ? (
          <Link href="/portfolio" aria-label={`Open ${account.display_name}'s portfolio`} className="grid size-9 place-items-center rounded-lg bg-[#8fb5ff] text-[11px] font-extrabold text-[#080b10] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff] focus-visible:ring-offset-2 focus-visible:ring-offset-[#080b10]">{initials(account.display_name)}</Link>
        ) : (
          <AuthTrigger className="h-9 rounded-lg bg-[#8fb5ff] px-4 text-[11px] font-extrabold text-[#080b10] hover:bg-[#a9c6ff] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff] focus-visible:ring-offset-2 focus-visible:ring-offset-[#080b10]">Sign in</AuthTrigger>
        )}
      </div>
    </header>
    <section aria-label="Highest-valued player stocks by current price" className="group flex h-9 overflow-hidden border-b border-[#202630] bg-[#0b0f15] text-[11px] font-medium tracking-[0.01em] tabular-nums slashed-zero">
      {[0,1].map(groupIndex => <div key={groupIndex} aria-hidden={groupIndex === 1} className="flex min-w-max shrink-0 animate-ticker items-stretch motion-reduce:animate-none group-hover:[animation-play-state:paused] group-focus-within:[animation-play-state:paused]">{tickerStocks.map((stock, index) => <Link prefetch={false} key={`${groupIndex}-${stock.id}`} href={`/instrument/${stock.id}`} tabIndex={groupIndex === 1 ? -1 : 0} className="flex items-center border-r border-[#202630] px-6 whitespace-nowrap text-[#87919d] hover:bg-white/[0.03] hover:text-white focus:bg-white/[0.03] focus:outline-none"><span className="mr-2.5 font-extrabold text-[#c1c8d0]">{String(index + 1).padStart(2,"0")}</span>{stock.symbol}<b className="mx-2 text-white">{formatCurrency(stock.price)}</b><em className={`not-italic ${stock.change >= 0 ? "text-[#35d07f]" : "text-[#f16d73]"}`}>{stock.change >= 0 ? "▲" : "▼"} {formatPercent(stock.change)}</em></Link>)}</div>)}
    </section>
  </>;
}

function SignOutButton() {
  return <form action="/api/auth/logout" method="post"><button type="submit" className="mt-3 text-[11px] font-bold text-[#7f8995] hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">Sign out</button></form>;
}

function NavIcon({ kind }: { kind: "portfolio" | "orders" | "history" | "leaderboard" }) {
  const common = "size-4 shrink-0";
  if (kind === "leaderboard") return <svg aria-hidden="true" viewBox="0 0 20 20" className={common} fill="none"><path d="M4 16V10h3.5v6M8.25 16V5h3.5v11M12.5 16v-4H16v4M3 16.5h14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>;
  if (kind === "portfolio") return <svg aria-hidden="true" viewBox="0 0 20 20" className={common} fill="none"><rect x="3" y="4" width="14" height="12" rx="2" stroke="currentColor" strokeWidth="1.5"/><path d="M6 8h8M6 12h5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>;
  if (kind === "orders") return <svg aria-hidden="true" viewBox="0 0 20 20" className={common} fill="none"><path d="M5 6h10m0 0-3-3m3 3-3 3M15 14H5m0 0 3 3m-3-3 3-3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>;
  return <svg aria-hidden="true" viewBox="0 0 20 20" className={common} fill="none"><circle cx="10" cy="10" r="7" stroke="currentColor" strokeWidth="1.5"/><path d="M10 6v4l2.5 1.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>;
}

function Sidebar({ active, account }: { active: ShellSection; account: Account }) {
  return <aside className="sticky top-[104px] hidden h-[calc(100vh-104px)] flex-col border-r border-[#202630] bg-[#090c11] px-4 py-7 lg:flex">
    <Label>Your account</Label>
    <Link href="/portfolio" className={`mb-0.5 flex h-10 items-center gap-3 rounded-lg px-3 text-xs font-bold ${active === "portfolio" ? "bg-[#8fb5ff]/[0.08] text-white" : "text-[#7c8693] hover:bg-white/[0.03] hover:text-white"}`}><span className={active === "portfolio" ? "text-[#8fb5ff]" : "text-[#626c79]"}><NavIcon kind="portfolio" /></span>Portfolio</Link>
    <Link href="/portfolio#activity" className="mb-0.5 flex h-10 items-center gap-3 rounded-lg px-3 text-xs font-bold text-[#7c8693] hover:bg-white/[0.03] hover:text-white"><span className="text-[#626c79]"><NavIcon kind="orders" /></span>Orders</Link>
    <Link href="/portfolio#activity" className="mb-0.5 flex h-10 items-center gap-3 rounded-lg px-3 text-xs font-bold text-[#7c8693] hover:bg-white/[0.03] hover:text-white"><span className="text-[#626c79]"><NavIcon kind="history" /></span>History</Link>
    <div className="mt-6"><Label>Community</Label></div>
    <Link href="/leaderboard" className={`mb-0.5 flex h-10 items-center gap-3 rounded-lg px-3 text-xs font-bold ${active === "leaderboard" ? "bg-[#8fb5ff]/[0.08] text-white" : "text-[#7c8693] hover:bg-white/[0.03] hover:text-white"}`}><span className={active === "leaderboard" ? "text-[#8fb5ff]" : "text-[#626c79]"}><NavIcon kind="leaderboard" /></span>Leaderboard</Link>
    <div className="mt-auto rounded-xl border border-[#242c37] bg-[#0e131a] p-3.5"><span className="block truncate text-[11px] text-[#737d89]">{account.display_name}</span><strong className="my-1.5 block text-lg tabular-nums slashed-zero">{formatCurrency(account.portfolio.cash_balance)}</strong><Link href="/portfolio" className="text-[11px] font-bold text-[#8fb5ff]">View portfolio →</Link><SignOutButton /></div>
  </aside>;
}

export function Shell({ active, account, tickerStocks, searchInstruments, children, initialAuthMode = null }: { active: ShellSection; account: Account | null; tickerStocks: TickerStock[]; searchInstruments: Instrument[]; children: ReactNode; initialAuthMode?: AuthMode | null }) {
  return <main className="min-h-screen bg-[#080b10] font-sans text-sm text-[#edf1f5]"><Header active={active} account={account} tickerStocks={tickerStocks} searchInstruments={searchInstruments}/><div className={account ? "grid lg:grid-cols-[224px_minmax(0,1fr)]" : "min-w-0"}>{account && <Sidebar active={active} account={account}/>} {children}</div>{!account && <AuthDialog initialMode={initialAuthMode}/>}</main>;
}

export const panel = "overflow-hidden rounded-xl border border-[#222a35] bg-[#0e131a]";
