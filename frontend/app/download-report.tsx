"use client";

import { Download, Loader2 } from "lucide-react";
import { useState } from "react";
import { API } from "./lib";
import type { EmailResult } from "./types";

/** The last thing on the page: a one-page PDF of the verdict, score and findings. Built in memory by the server, never stored. */
export function DownloadReport({ result }: { result: EmailResult }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function download() {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API}/report`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(result),
      });
      if (!res.ok) throw new Error(`The report could not be made (${res.status}).`);
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = `epiderm-report-${new Date().toISOString().slice(0, 10)}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="tg-card flex flex-wrap items-center justify-between gap-4 p-5" aria-label="Download report">
      <div>
        <p className="text-base font-semibold">Keep a record</p>
        <p className="mt-0.5 text-sm text-zinc-600 dark:text-zinc-300">
          A PDF with the verdict, score, findings and next steps. It leaves out the full text of your message and document,
          so it is safe to send to your bank or the cybercrime portal.
        </p>
        {error && <p className="mt-1 text-sm text-red-600 dark:text-red-400" role="alert">{error}</p>}
      </div>
      <button
        type="button"
        onClick={download}
        disabled={busy}
        className="inline-flex items-center gap-2 rounded-lg bg-zinc-900 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-zinc-700 disabled:opacity-60 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-white"
      >
        {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Download className="size-4" aria-hidden />}
        {busy ? "Making PDF…" : "Download report"}
      </button>
    </section>
  );
}
