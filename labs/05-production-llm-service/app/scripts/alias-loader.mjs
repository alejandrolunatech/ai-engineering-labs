// Resolve hook for `npm run inspect-pr`. Node built-ins only, no new package.
//
// Node runs the TypeScript sources directly (built-in type stripping). This hook
// only maps the "@/..." import alias from tsconfig.json to files under the app
// root. "server-only" is resolved by the --conditions=react-server flag in the
// npm script, which selects that package's no-op entry.
import { existsSync } from "node:fs";
import { registerHooks } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";

const APP_ROOT = fileURLToPath(new URL("../", import.meta.url));

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.startsWith("@/")) {
      const base = APP_ROOT + specifier.slice(2);
      for (const candidate of [`${base}.ts`, `${base}/index.ts`, base]) {
        if (existsSync(candidate)) {
          return { url: pathToFileURL(candidate).href, shortCircuit: true };
        }
      }
    }
    return nextResolve(specifier, context);
  },
});
