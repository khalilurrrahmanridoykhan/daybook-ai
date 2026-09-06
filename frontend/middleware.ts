import { NextResponse, type NextRequest } from "next/server";

// Optimistic only -- same split as Daybook's own proxy.ts: this just
// avoids a flash of the chat UI before redirecting; the backend's
// require_session dependency is the real enforcement on every API call.
// Only reliable when frontend and backend share an origin (this
// project's own nginx setup at ai.krrkhan.com does exactly that) -- the
// old two-port SSH-tunnel dev setup has separate cookie jars per origin,
// so this check can't see the backend's cookie there.
const SESSION_COOKIE = "daybook_ai_session";

export function middleware(request: NextRequest) {
  const hasSession = request.cookies.has(SESSION_COOKIE);
  const isLoginPage = request.nextUrl.pathname === "/login";

  if (!hasSession && !isLoginPage) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  if (hasSession && isLoginPage) {
    return NextResponse.redirect(new URL("/", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
