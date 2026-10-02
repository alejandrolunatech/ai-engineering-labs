import { getConfig } from "@/lib/config";

// GET /api/health — process and configuration health only.
// It makes no external call and says nothing about GitHub or LLM availability:
// a 200 here does not mean an analysis would succeed.

export const dynamic = "force-dynamic";

export function GET(): Response {
  const result = getConfig();
  if (!result.ok) {
    return Response.json({ status: "error", config: "invalid" }, { status: 503 });
  }
  return Response.json(
    { status: "ok", config: "valid", schemaVersion: result.config.schemaVersion },
    { status: 200, headers: { "Cache-Control": "no-store" } },
  );
}
