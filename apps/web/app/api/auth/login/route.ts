import { authenticateRequest } from "@/lib/auth-proxy";

export async function POST(request: Request) {
  return authenticateRequest(request, "/v1/auth/login");
}
