import { NextRequest, NextResponse } from "next/server";
import { getPriceHistory, type PriceHistoryRange } from "@/lib/api";

const validRanges = new Set<PriceHistoryRange>(["1D", "1W", "1M", "3M", "1Y", "ALL"]);

type RouteContext = { params: Promise<{ id: string }> };

export async function GET(request: NextRequest, { params }: RouteContext) {
  const { id } = await params;
  const requestedRange = request.nextUrl.searchParams.get("range") ?? "1W";

  if (!validRanges.has(requestedRange as PriceHistoryRange)) {
    return NextResponse.json({ message: "Unsupported price history range" }, { status: 400 });
  }

  try {
    const history = await getPriceHistory(id, requestedRange as PriceHistoryRange);
    return NextResponse.json(history);
  } catch {
    return NextResponse.json({ message: "Price history is temporarily unavailable" }, { status: 502 });
  }
}
