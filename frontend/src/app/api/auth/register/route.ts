import { NextResponse, type NextRequest } from "next/server";

import { callBackend, grantFrom, isSameOrigin, readJsonBody, rejectCrossSite } from "@/lib/server/auth-proxy";

export async function POST(request: NextRequest): Promise<NextResponse> {
  if (!isSameOrigin(request)) return rejectCrossSite();
  const body = await readJsonBody(request);
  if (body instanceof NextResponse) return body;
  return grantFrom(await callBackend("/v1/auth/register", body, request));
}
