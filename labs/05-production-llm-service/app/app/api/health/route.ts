import { getConfig } from "@/lib/config";

// GET /api/health — process and configuration health only.
// It makes no external call and says nothing about GitHub or LLM availability:
// a 200 here does not mean an analysis would succeed. githubAuth only says
// whether a token is configured ("token" | "anonymous"), never its value.
// llm says whether a model is configured and which one; never the key.
// service is the kill switch; rateLimit names the store ("not_configured" on
// Vercel means analysis is refused) and the limits, never the store's URL.

export const dynamic = "force-dynamic";

export function GET(): Response {
  const result = getConfig();
  if (!result.ok) {
    return Response.json({ status: "error", config: "invalid" }, { status: 503 });
  }
  return Response.json(
    {
      status: "ok",
      config: "valid",
      schemaVersion: result.config.schemaVersion,
      githubAuth: result.config.githubAuth,
      llm:
        result.config.llm.status === "configured"
          ? { status: "configured", model: result.config.llm.model, reasoningEffort: result.config.llm.reasoningEffort }
          : { status: "not_configured" },
      service: result.config.serviceEnabled ? "enabled" : "disabled",
      rateLimit: { backend: result.config.rateLimit.backend, ...result.config.rateLimit.limits },
    },
    { status: 200, headers: { "Cache-Control": "no-store" } },
  );
}
