import type { NextConfig } from "next";

// Phase 6 security headers, on every response.
//
// The CSP is the Next.js "without nonces" policy: scripts and styles only from
// this origin, no plugins, no framing, no form posts elsewhere, and the browser
// may only call this origin (connect-src). 'unsafe-inline' stays on script-src
// because Next.js writes inline bootstrap scripts and the pages are static; a
// nonce would force every page to render per request. XSS defense still rests
// on React escaping and on never using dangerouslySetInnerHTML
// (tests/source-guards.test.ts). Vercel's preview toolbar is blocked by this
// policy on preview deployments; that is expected.
const isDev = process.env.NODE_ENV === "development";

export const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' blob: data:",
  "font-src 'self'",
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "upgrade-insecure-requests",
].join("; ");

export const SECURITY_HEADERS = [
  { key: "Content-Security-Policy", value: CONTENT_SECURITY_POLICY },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()" },
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
];

const nextConfig: NextConfig = {
  poweredByHeader: false,
  async headers() {
    return [{ source: "/(.*)", headers: SECURITY_HEADERS }];
  },
};

export default nextConfig;
