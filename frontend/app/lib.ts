export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8001";

/** Opens this person's private container. Returns its session id, or null when no container is available. */
export async function openSession(): Promise<string | null> {
  const res = await fetch(`${API}/sessions`, { method: "POST" });
  if (!res.ok) throw new Error(`sessions returned ${res.status}`);
  const body = (await res.json()) as { session_id: string | null };
  return body.session_id;
}

/** Deletes the container. `keepalive` lets the request finish even while the tab is closing. */
export function closeSession(id: string): void {
  try {
    void fetch(`${API}/sessions/${id}/close`, { method: "POST", keepalive: true }).catch(() => undefined);
  } catch {
    /* nothing to do: the server also closes idle sessions */
  }
}

/**
 * Reads a newline-delimited JSON progress stream from the server: {"stage": "..."} events as each real stage begins,
 * then {"stage": "done", "result": ...} or {"stage": "error", "detail": "..."}. Returns the result.
 */
export async function readStream<T>(res: Response, onStage: (stage: string) => void): Promise<T> {
  if (!res.body) throw new Error("The server sent no answer.");
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: T | undefined;
  let finished = false;
  while (!finished) {
    const chunk = await reader.read();
    finished = chunk.done;
    buffer += decoder.decode(chunk.value, { stream: !chunk.done });
    let newline = buffer.indexOf("\n");
    while (newline >= 0) {
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      newline = buffer.indexOf("\n");
      if (!line) continue;
      const event = JSON.parse(line) as { stage: string; result?: T; detail?: string };
      if (event.stage === "error") throw new Error(event.detail ?? "The check failed.");
      if (event.stage === "done") result = event.result;
      else onStage(event.stage);
    }
  }
  if (result === undefined) throw new Error("The check ended without a result.");
  return result;
}
