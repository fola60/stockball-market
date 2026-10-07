import type { NextRequest } from "next/server";
import { proxyInstrumentImage } from "@/lib/image-proxy";

type RouteContext = { params: Promise<{ id: string }> };

export async function GET(request: NextRequest, { params }: RouteContext) {
  const { id } = await params;
  return proxyInstrumentImage(request, id, "club-badge");
}
