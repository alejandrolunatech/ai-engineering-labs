// Production smoke test: npm run smoke -- <base URL> [--analyze]
//
// Without --analyze it costs nothing: home page, headers, health, and one
// request the server must refuse before any GitHub or model call.
// --analyze also explains one known public PR: one model call (~0.0006 USD)
// and one request off your hourly rate limit.
// Previews behind Vercel Authentication answer 401 here; check those by hand.

import { runSmoke } from "@/scripts/smoke-lib";

async function main(): Promise<number> {
  const args = process.argv.slice(2);
  const analyze = args.includes("--analyze");
  const bases = args.filter((a) => a !== "--analyze");
  if (bases.length !== 1 || !/^https?:\/\//.test(bases[0])) {
    console.error("usage: npm run smoke -- <https://your-deployment> [--analyze]");
    return 2;
  }
  // The operator's own deployment; runSmoke only calls fixed paths on it.
  const checks = await runSmoke(bases[0], { analyze }, (url, init) => fetch(url, { ...init, cache: "no-store" }));
  for (const c of checks) console.log(`${c.ok ? "PASS" : "FAIL"}  ${c.name}: ${c.detail}`);
  const failed = checks.filter((c) => !c.ok).length;
  console.log(failed === 0 ? "\nsmoke test passed" : `\nsmoke test FAILED (${failed} check${failed === 1 ? "" : "s"})`);
  return failed === 0 ? 0 : 1;
}

main().then(
  (code) => process.exit(code),
  () => {
    console.error("smoke test could not run (network error or bad URL)");
    process.exit(1);
  },
);
