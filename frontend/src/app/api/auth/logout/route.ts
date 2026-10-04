import { NextResponse, type NextRequest } from "next/server";

import {
  REFRESH_COOKIE,
  callBackend,
  clearRefreshCookie,
  isSameOrigin,
  rejectCrossSite,
} from "@/lib/server/auth-proxy";

export async function POST(request: NextRequest): Promise<NextResponse> {
  if (!isSameOrigin(request)) return rejectCrossSite();

  const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value;
  if (refreshToken) {
    // Revokes the token server-side, so a copy of the cookie is worthless too. Its outcome is
    // deliberately ignored: an unreachable backend must not trap the student in a session they
    // asked to end.
    await callBackend("/v1/auth/logout", JSON.stringify({ refresh_token: refreshToken }), request);
  }
  return clearRefreshCookie(new NextResponse(null, { status: 204 }));
}
