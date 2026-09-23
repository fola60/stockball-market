import { NextResponse } from "next/server";
import { ApiError, apiRequest } from "@/lib/api";

export async function POST(request: Request) {
  try {
    const result = await apiRequest("/v1/orders/quote", {
      method: "POST",
      body: await request.text(),
    });
    return NextResponse.json(result);
  } catch (error) {
    if (error instanceof ApiError) return NextResponse.json(error.body, { status: error.status });
    return NextResponse.json(
      { code: "service_unavailable", message: "Trading is temporarily unavailable." },
      { status: 502 },
    );
  }
}
