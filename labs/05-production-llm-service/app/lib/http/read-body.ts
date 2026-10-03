// Reads a body with a hard byte cap.
//
// Content-Length is only used to reject early. It is never trusted to allow a
// body: the stream itself is counted and reading stops as soon as the cap is
// exceeded, so a missing or lying header cannot push more bytes through.
//
// readStreamWithLimit is shared by the inbound request body (this file) and
// GitHub responses (lib/github/client.ts).

export type ReadStreamResult = { ok: true; bytes: Uint8Array } | { ok: false };

export async function readStreamWithLimit(
  stream: ReadableStream<Uint8Array> | null,
  maxBytes: number,
): Promise<ReadStreamResult> {
  const chunks: Uint8Array[] = [];
  let total = 0;

  if (stream) {
    const reader = stream.getReader();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > maxBytes) {
        await reader.cancel().catch(() => {});
        return { ok: false };
      }
      chunks.push(value);
    }
  }

  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return { ok: true, bytes };
}

export function declaredLengthExceeds(headers: Headers, maxBytes: number): boolean {
  const declared = headers.get("content-length");
  return declared !== null && /^\d+$/.test(declared) && Number(declared) > maxBytes;
}

export type ReadBodyResult =
  | { ok: true; text: string }
  | { ok: false; reason: "too_large" | "invalid_encoding" };

export async function readBodyWithLimit(
  request: Request,
  maxBytes: number,
): Promise<ReadBodyResult> {
  if (declaredLengthExceeds(request.headers, maxBytes)) {
    return { ok: false, reason: "too_large" };
  }

  const read = await readStreamWithLimit(request.body, maxBytes);
  if (!read.ok) {
    return { ok: false, reason: "too_large" };
  }

  try {
    return { ok: true, text: new TextDecoder("utf-8", { fatal: true }).decode(read.bytes) };
  } catch {
    return { ok: false, reason: "invalid_encoding" };
  }
}
