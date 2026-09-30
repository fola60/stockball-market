import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";


async function renderedHome() {
  // The portal is a client-rendered page, so `next build` prerenders it to static HTML.
  return readFile(new URL("../.next/server/app/index.html", import.meta.url), "utf8");
}


test("server-renders the Stockball operations portal", async () => {
  const html = await renderedHome();
  assert.match(html, /<title>Stockball Admin<\/title>/i);
  assert.match(html, /Operation runs/);
  assert.match(html, /Synthetic traders/);
  assert.doesNotMatch(html, /Your site is taking shape|Building your site/);
});


test("keeps features independently modular", async () => {
  const files = [
    "../app/page.tsx",
    "../features/runs/RunsView.tsx",
    "../features/processes/ProcessesView.tsx",
    "../features/ingestion/IngestionView.tsx",
    "../features/traders/TradersView.tsx",
    "../features/trades/TradesView.tsx",
    "../lib/constants.ts",
  ];
  const sources = await Promise.all(
    files.map((path) => readFile(new URL(path, import.meta.url), "utf8")),
  );
  for (const source of sources.slice(1, 6)) assert.match(source, /export function/);
  assert.match(sources[6], /Social feeds/);
  assert.match(sources[3], /Pipeline health/);
});
