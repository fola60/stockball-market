import type { NextRequest } from "next/server";
import { proxyTeamBadge } from "@/lib/image-proxy";

type RouteContext = { params: Promise<{ id: string }> };

export async function GET(request: NextRequest, { params }: RouteContext) {
  const { id } = await params;
  return proxyTeamBadge(request, id);
}
