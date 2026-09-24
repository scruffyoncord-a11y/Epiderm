"use client";

import { useState } from "react";
import { Card, SignalList } from "./components";
import type { DocumentReport } from "./types";
import { Waiting } from "./waiting";

const MAX_BYTES = 10 * 1024 * 1024;
const DEFAULT_ACCEPT = ".pdf,.docx,.xlsx,.pptx,.jpg,.jpeg,.png";

type Props = {
  apiBase: string;
  heading?: string;
  intro?: string;
  accept?: string;
  fileLabel?: string;
  showVendor?: boolean;
  buttonLabel?: string;
};

export function DocumentCheck({
  apiBase,
  heading = "Check a document",
  intro = "Upload an invoice, letter or photo of one. TrustGuard reads what the file says about itself: which program made it, when, whether it was saved again afterwards. The file is read in memory and never stored.",
  accept = DEFAULT_ACCEPT,
  fileLabel = "File (PDF, Word, Excel, PowerPoint, JPG or PNG, up to 10 MB)",
  showVendor = true,
  buttonLabel = "Check document",
}: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [vendor, setVendor] = useState("");
  const [report, setReport] = useState<DocumentReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function pick(f: File | null) {
    setReport(null);
    setError(null);
    if (f && f.size > MAX_BYTES) {
      setFile(null);
      setError("That file is larger than 10 MB.");
      return;
    }
    setFile(f);
  }

  async function run() {
    if (!file) return;
    setLoading(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      if (vendor.trim()) form.append("vendor", vendor.trim());
      const res = await fetch(`${apiBase}/analyze-document`, { method: "POST", body: form });
      if (!res.ok) throw new Error(res.status === 413 ? "That file is too large." : `The check failed (${res.status}).`);
      setReport(await res.json());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section aria-labelledby="doc-label">
      <h2 id="doc-label" className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
        {heading}
      </h2>
      <p className="mt-2 text-sm text-zinc-500">{intro}</p>

      <div className="mt-3 flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor="doc-file" className="block text-sm text-zinc-500">
            {fileLabel}
          </label>
          <input
            id="doc-file"
            type="file"
            accept={accept}
            onChange={(e) => pick(e.target.files?.[0] ?? null)}
            className="mt-1 block text-sm"
          />
        </div>
        {showVendor && (
        <div>
          <label htmlFor="doc-vendor" className="block text-sm text-zinc-500">
            Vendor name on the invoice (optional)
          </label>
          <input
            id="doc-vendor"
            type="text"
            value={vendor}
            onChange={(e) => setVendor(e.target.value)}
            maxLength={120}
            placeholder="e.g. Sunrise Traders"
            className="mt-1 rounded-lg border border-zinc-300 bg-transparent p-2 text-sm dark:border-zinc-700"
          />
        </div>
        )}
        <button
          type="button"
          onClick={run}
          disabled={!file || loading}
          className="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-40 dark:bg-zinc-100 dark:text-zinc-900"
        >
          {loading ? "Reading…" : buttonLabel}
        </button>
      </div>

      {loading && <Waiting label="Reading the file details…" note="This is usually quick." />}

      {error && (
        <p className="mt-3 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-900" role="alert">
          {error}
        </p>
      )}

      {report && (
        <div className="mt-4 space-y-4">
          <p className="text-sm" role="status">
            <strong>{report.filename || "File"}</strong> · detected as {report.format} · {(report.size_bytes / 1024).toFixed(0)} KB
            <span className="block mt-1 text-zinc-500">{report.summary}</span>
          </p>

          {Object.keys(report.fields).length > 0 && (
            <Card title="What the file says about itself">
              <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-2">
                {Object.entries(report.fields).map(([k, v]) => (
                  <div key={k}>
                    <dt className="text-xs text-zinc-500">{k}</dt>
                    <dd className="break-words">{v}</dd>
                  </div>
                ))}
              </dl>
            </Card>
          )}

          <Card title="What stands out" aside={<span className="text-xs text-zinc-500">strongest first</span>}>
            <SignalList signals={report.signals} />
          </Card>

          {report.could_not_check.length > 0 && (
            <Card title="What we could not check">
              <ul className="list-disc space-y-1 pl-5 text-sm">
                {report.could_not_check.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-zinc-500">Unchecked is not the same as suspicious.</p>
            </Card>
          )}
        </div>
      )}
    </section>
  );
}
