import { beforeEach } from "vitest";
import { resetMemoryStore } from "@/lib/rate-limit";

// Every test starts with empty in-memory rate-limit counters, so tests that
// send many requests never limit each other.
beforeEach(() => resetMemoryStore());
