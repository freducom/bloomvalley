import { NextRequest, NextResponse } from "next/server";

/**
 * Inject X-API-Key header into all /api/* requests before the Next.js
 * rewrite forwards them to the backend. The key is server-side only —
 * it never reaches the browser.
 */
export function middleware(request: NextRequest) {
  const apiKey = process.env.API_KEY;
  if (!apiKey) return NextResponse.next();

  const headers = new Headers(request.headers);
  headers.set("X-API-Key", apiKey);

  return NextResponse.next({ request: { headers } });
}

export const config = {
  matcher: "/api/:path*",
};
