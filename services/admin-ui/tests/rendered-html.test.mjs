import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";


async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}


test("server-renders the Stockball operations portal", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /<title>Stockball Dev Portal<\/title>/i);
  assert.match(html, /Operation runs/);
  assert.match(html, /Synthetic traders/);
  assert.doesNotMatch(html, /Your site is taking shape|Building your site/);
});


test("keeps the page shell small and features independently modular", async () => {
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
  assert.ok(sources[0].split("\n").length < 250);
  for (const source of sources.slice(1, 6)) assert.match(source, /export function/);
  assert.match(sources[6], /Social feeds/);
  assert.match(sources[3], /Pipeline health/);
});
