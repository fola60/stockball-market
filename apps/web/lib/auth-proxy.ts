import { NextResponse } from "next/server";
import { SESSION_COOKIE, sessionCookieOptions } from "@/lib/session";

const API_URL = process.env.STOCKBALL_API_URL ?? "http://localhost:8000";

/**
 * The visitor's address, as the reverse proxy in front of the site reported it. The API limits
 * sign-ups and sign-ins per visitor, and without this every visitor would look like this server.
 */
function visitorAddress(request: Request): string | null {
  const forwarded = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim();
  return forwarded || request.headers.get("x-real-ip");
}

export async function authenticateRequest(request: Request, path: string) {
  const address = visitorAddress(request);
  const response = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(address ? { "X-Forwarded-For": address } : {}) },
    body: await request.text(),
    cache: "no-store",
  });
  const body = await response.json();
  if (!response.ok) {
    const retryAfter = response.headers.get("retry-after");
    return NextResponse.json(body, {
      status: response.status,
      headers: retryAfter ? { "Retry-After": retryAfter } : undefined,
    });
  }

  const result = NextResponse.json({ account: body.account });
  result.cookies.set(SESSION_COOKIE, body.session_token, {
    ...sessionCookieOptions,
    expires: new Date(body.expires_at),
  });
  return result;
}
