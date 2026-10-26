import "server-only";
import { createHash } from "node:crypto";
import { isIP } from "node:net";
import { z } from "zod";
import type { RateLimitConfig } from "@/lib/config";

// Phase 6: anonymous rate limits, checked BEFORE any GitHub or model call.
//
// Two layers, both fixed windows counted in a shared store:
//   1. per client: at most perIpPerHour and perIpPerDay analyses per client key;
//   2. global: at most globalPerDay analyses for the whole service. With the
//      worst-case cost of one request (LEARNING-NOTES Phase 6) this bounds the
//      app's daily model spend. The provider's prepaid credit stays the final cap.
// The global counter only moves when the client layer allowed the request, so
// one noisy client cannot use up everybody's daily budget.
//
// Stores:
//   - "upstash": Upstash Redis over its REST API (plain fetch, no SDK). Shared by
//     every Vercel function instance, so the limit holds across instances.
//   - "memory": a Map in this process. Local development and tests only:
//     config.ts refuses it on Vercel.
// Any store failure is a deny (fail closed): the route answers 503, never "allowed".
//
// What a client key is, and is not: on Vercel it is the client IP that Vercel's
// edge writes into x-real-ip (Vercel overwrites client-sent values). IPv6 is
// counted per /64, because one host usually owns a whole /64. The key is a
// SHA-256 digest of that address: the raw IP never reaches the store or the
// logs. A digest of an IPv4 address can be reversed by trying all of them, so it
// is pseudonymous, not anonymous; keys expire within a day. An IP is not an
// identity: NAT, VPNs and botnets share or rotate it. That is why the global
// cap exists.

export type Counter = { key: string; ttlSec: number };

// Increments each counter (creating it with its TTL when new) and returns the
// new counts in order, or null when the store could not answer.
export interface RateLimitStore {
  increment(counters: Counter[]): Promise<number[] | null>;
}

export type RateLimitDecision =
  | { ok: true }
  | { ok: false; reason: "rate_limited_ip" | "rate_limited_global"; retryAfterSec: number }
  | { ok: false; reason: "rate_limiter_unavailable" };

const HOUR = 3_600;
const DAY = 86_400;
const KEY_PREFIX = "changebrief:rl:v1";

function window(nowSec: number, lengthSec: number): { id: number; resetSec: number } {
  const id = Math.floor(nowSec / lengthSec);
  return { id, resetSec: Math.max(1, (id + 1) * lengthSec - nowSec) };
}

export async function checkRateLimit(
  clientKey: string,
  limits: RateLimitConfig["limits"],
  store: RateLimitStore,
  nowMs: number = Date.now(),
): Promise<RateLimitDecision> {
  const now = Math.floor(nowMs / 1000);
  const hour = window(now, HOUR);
  const day = window(now, DAY);

  const client = await store.increment([
    { key: `${KEY_PREFIX}:ip:${clientKey}:h:${hour.id}`, ttlSec: HOUR },
    { key: `${KEY_PREFIX}:ip:${clientKey}:d:${day.id}`, ttlSec: DAY },
  ]);
  if (client === null || client.length !== 2) return { ok: false, reason: "rate_limiter_unavailable" };
  const [perHour, perDay] = client;
  if (perDay > limits.perIpPerDay) return { ok: false, reason: "rate_limited_ip", retryAfterSec: day.resetSec };
  if (perHour > limits.perIpPerHour) return { ok: false, reason: "rate_limited_ip", retryAfterSec: hour.resetSec };

  const global = await store.increment([{ key: `${KEY_PREFIX}:global:d:${day.id}`, ttlSec: DAY }]);
  if (global === null || global.length !== 1) return { ok: false, reason: "rate_limiter_unavailable" };
  if (global[0] > limits.globalPerDay) return { ok: false, reason: "rate_limited_global", retryAfterSec: day.resetSec };

  return { ok: true };
}

// ---------------------------------------------------------------------------
// Client key

// "a:b::c" -> 8 full hextets. Input is already known to be IPv6 (isIP === 6).
function ipv6Hextets(ip: string): string[] {
  let address = ip.toLowerCase().split("%", 1)[0];
  // An embedded IPv4 tail (::ffff:1.2.3.4) becomes two hextets.
  const v4 = address.match(/(\d+)\.(\d+)\.(\d+)\.(\d+)$/);
  if (v4) {
    const [a, b, c, d] = v4.slice(1).map(Number);
    address = address.slice(0, -v4[0].length) + `${((a << 8) | b).toString(16)}:${((c << 8) | d).toString(16)}`;
  }
  const [head, tail] = address.split("::");
  const left = head === "" ? [] : head.split(":");
  const right = tail === undefined || tail === "" ? [] : tail.split(":");
  const fill = tail === undefined ? [] : Array(8 - left.length - right.length).fill("0");
  return [...left, ...fill, ...right].map((h) => h.padStart(4, "0"));
}

// The address the limit counts: IPv4 as is, IPv6 cut to its /64.
export function rateLimitSubject(ip: string): string | null {
  const version = isIP(ip);
  if (version === 4) return ip;
  if (version === 6) return `${ipv6Hextets(ip).slice(0, 4).join(":")}::/64`;
  return null;
}

// The client key for a request. On Vercel only Vercel-written headers count;
// off Vercel (local development) every request is the same client.
export function clientKey(headers: Headers, onVercel: boolean): string {
  if (!onVercel) return "local";
  const ip = (headers.get("x-real-ip") ?? headers.get("x-forwarded-for")?.split(",", 1)[0] ?? "").trim();
  const subject = rateLimitSubject(ip);
  // No usable address: all such requests share one strict bucket.
  if (subject === null) return "unknown";
  return createHash("sha256").update(`changebrief-rl:${subject}`).digest("hex").slice(0, 32);
}

// ---------------------------------------------------------------------------
// Stores

type Entry = { count: number; expiresAtMs: number };
const memory = new Map<string, Entry>();

export const memoryStore: RateLimitStore = {
  async increment(counters) {
    const now = Date.now();
    return counters.map(({ key, ttlSec }) => {
      const entry = memory.get(key);
      const live = entry !== undefined && entry.expiresAtMs > now ? entry : { count: 0, expiresAtMs: now + ttlSec * 1000 };
      live.count += 1;
      memory.set(key, live);
      return live.count;
    });
  },
};

// Tests only.
export function resetMemoryStore(): void {
  memory.clear();
}

export const UPSTASH_TIMEOUT_MS = 1_000;

const PipelineReply = z.array(z.union([z.strictObject({ result: z.unknown() }), z.strictObject({ error: z.string() })]));

// Upstash REST pipeline: for each counter, SET key 0 EX ttl NX (start the
// window once) then INCR key. One HTTP request per increment() call.
export function upstashStore(url: string, token: string): RateLimitStore {
  const endpoint = `${url.replace(/\/+$/, "")}/pipeline`;
  return {
    async increment(counters) {
      const commands = counters.flatMap(({ key, ttlSec }) => [
        ["SET", key, "0", "EX", String(ttlSec), "NX"],
        ["INCR", key],
      ]);
      try {
        const res = await fetch(endpoint, {
          method: "POST",
          headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
          body: JSON.stringify(commands),
          redirect: "error",
          cache: "no-store",
          signal: AbortSignal.timeout(UPSTASH_TIMEOUT_MS),
        });
        if (!res.ok) return null;
        const reply = PipelineReply.safeParse(await res.json());
        if (!reply.success || reply.data.length !== commands.length) return null;
        const counts: number[] = [];
        for (let i = 1; i < reply.data.length; i += 2) {
          const r = reply.data[i];
          if (!("result" in r) || typeof r.result !== "number" || !Number.isInteger(r.result) || r.result < 1) return null;
          counts.push(r.result);
        }
        return counts;
      } catch {
        // Timeout, network error, bad JSON: never log it, it may hold the URL.
        return null;
      }
    },
  };
}

// The store for this config, or null when none is configured. The Upstash
// URL and token VALUES are read only here; config.ts checks presence.
export function storeFor(config: RateLimitConfig): RateLimitStore | null {
  if (config.backend === "memory") return memoryStore;
  if (config.backend !== "upstash") return null;
  const url = (process.env.UPSTASH_REDIS_REST_URL || process.env.KV_REST_API_URL || "").trim();
  const token = (process.env.UPSTASH_REDIS_REST_TOKEN || process.env.KV_REST_API_TOKEN || "").trim();
  if (url === "" || token === "") return null;
  return upstashStore(url, token);
}
