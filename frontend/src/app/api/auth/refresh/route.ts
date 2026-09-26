import { NextResponse, type NextRequest } from "next/server";

import {
  REFRESH_COOKIE,
  callBackend,
  clearRefreshCookie,
  grantFrom,
  isSameOrigin,
  rejectCrossSite,
} from "@/lib/server/auth-proxy";

export async function POST(request: NextRequest): Promise<NextResponse> {
  if (!isSameOrigin(request)) return rejectCrossSite();

  const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value;
  if (!refreshToken) {
    // Not an error, just a visitor: every signed-out page load asks, and a 401 here would put an
    // error in the console of every one of them.
    return new NextResponse(null, { status: 204 });
  }

  const upstream = await callBackend(
    "/v1/auth/refresh",
    JSON.stringify({ refresh_token: refreshToken }),
    request,
  );
  if (upstream.status === 401 || upstream.status === 422) {
    // Expired, revoked, or reused: the cookie is dead weight now. A 429 or a 5xx says nothing
    // about the token, so those keep it.
    return clearRefreshCookie(
      NextResponse.json(
        { error: { code: "unauthenticated", message: "Session expired." } },
        { status: 401 },
      ),
    );
  }
  return grantFrom(upstream);
}
