import { NextResponse } from "next/server";
import { SESSION_COOKIE, sessionCookieOptions, sessionToken } from "@/lib/session";

const API_URL = process.env.STOCKBALL_API_URL ?? "http://localhost:8000";

export async function POST(request: Request) {
  const token = await sessionToken();
  if (token) {
    await fetch(`${API_URL}/v1/auth/logout`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    }).catch(() => undefined);
  }
  const response = NextResponse.redirect(new URL("/login", request.url), 303);
  response.cookies.set(SESSION_COOKIE, "", { ...sessionCookieOptions, maxAge: 0 });
  return response;
}
