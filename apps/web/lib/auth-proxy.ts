import { NextResponse } from "next/server";
import { SESSION_COOKIE, sessionCookieOptions } from "@/lib/session";

const API_URL = process.env.STOCKBALL_API_URL ?? "http://localhost:8000";

export async function authenticateRequest(request: Request, path: string) {
  const response = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: await request.text(),
    cache: "no-store",
  });
  const body = await response.json();
  if (!response.ok) return NextResponse.json(body, { status: response.status });

  const result = NextResponse.json({ account: body.account });
  result.cookies.set(SESSION_COOKIE, body.session_token, {
    ...sessionCookieOptions,
    expires: new Date(body.expires_at),
  });
  return result;
}
