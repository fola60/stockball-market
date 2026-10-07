import type { NextRequest } from "next/server";

const API_URL = process.env.STOCKBALL_API_URL ?? "http://localhost:8000";
const INSTRUMENT_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type InstrumentImage = "player-image" | "club-badge";

/**
 * Serves an instrument's stored image from the web origin, since the API is only
 * reachable server-side. Pages request images with `?v=<content-hash prefix>`, so a
 * response whose ETag matches that version can be cached by the browser for good.
 */
export async function proxyInstrumentImage(request: NextRequest, id: string, image: InstrumentImage) {
  if (!INSTRUMENT_ID.test(id)) return new Response(null, { status: 404 });

  const ifNoneMatch = request.headers.get("if-none-match");
  let upstream: Response;
  try {
    upstream = await fetch(`${API_URL}/v1/instruments/${id}/${image}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(8_000),
      headers: ifNoneMatch ? { "If-None-Match": ifNoneMatch } : {},
    });
  } catch {
    return new Response(null, { status: 502, headers: { "Cache-Control": "no-store" } });
  }

  const etag = upstream.headers.get("etag");
  const version = request.nextUrl.searchParams.get("v");
  const pinned = Boolean(version && etag?.replaceAll('"', "").startsWith(version));
  const cacheControl = pinned
    ? "public, max-age=31536000, immutable"
    : upstream.headers.get("cache-control") ?? "public, max-age=3600";

  if (upstream.status === 304) {
    return new Response(null, { status: 304, headers: { ...(etag ? { ETag: etag } : {}), "Cache-Control": cacheControl } });
  }
  const contentType = upstream.headers.get("content-type") ?? "";
  if (!upstream.ok || !contentType.startsWith("image/")) {
    await upstream.body?.cancel();
    return new Response(null, {
      status: upstream.status === 404 ? 404 : 502,
      headers: { "Cache-Control": "no-store" },
    });
  }
  return new Response(upstream.body, {
    headers: { "Content-Type": contentType, ...(etag ? { ETag: etag } : {}), "Cache-Control": cacheControl },
  });
}
