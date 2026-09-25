"use client";

import { RotateCcw, Upload, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { AnalysisOverlay } from "./analysis-overlay";
import { Card, Checklist, DecisionBanner, DocumentReadingCard, IdentifiersCard, SignalList } from "./components";
import { readStream } from "./lib";
import { DownloadReport } from "./download-report";
import { RiskDashboard } from "./risk-dashboard";
import type { Config, DocumentReport } from "./types";

const MAX_BYTES = 10 * 1024 * 1024;
function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const DEFAULT_ACCEPT = ".pdf,.docx,.xlsx,.pptx,.jpg,.jpeg,.png";

type Stage = "started" | "container" | "reading" | "verifying";
type PlanStep = { key: Stage; label: string; detail: string };

/** The steps this check will really go through. Each maps to a stage the server reports; unused ones are left out. */
function buildPlan(o: { container: boolean; ownContainer: boolean; model: boolean; local: boolean; image: boolean }): PlanStep[] {
  const plan: PlanStep[] = [{ key: "started", label: "File received", detail: "Held in memory, never stored" }];
  if (o.container) {
    plan.push({
      key: "container",
      label: o.ownContainer ? "Opening it in your container" : "Opening a private container",
      detail: "Contents extracted with no network access",
    });
  }
  if (o.model) {
    plan.push({
      key: "reading",
      label: o.image ? "Reading the image" : "Reading the contents",
      detail: o.local ? "A model on this computer is reading it" : "The reasoning model is reading it",
    });
  }
  plan.push({ key: "verifying", label: "Verifying the evidence", detail: "Every claim is checked against the file" });
  return plan;
}

type Props = {
  apiBase: string;
  heading?: string;
  intro?: string;
  accept?: string;
  fileLabel?: string;
  showVendor?: boolean;
  buttonLabel?: string;
  uploadLabel?: string;
  sessionId?: string | null;
  onResultChange?: (has: boolean) => void;
};

export function DocumentCheck({
  apiBase,
  heading = "Check a document",
  intro = "Upload an invoice, letter or photo of one. Epiderm reads what the file says about itself (which program made it, when, whether it was saved again) and what it says: who is asking to be paid, where the money goes, and whether any tax or bank numbers are impossible. The file is read in memory and never stored.",
  accept = DEFAULT_ACCEPT,
  fileLabel = "File (PDF, Word, Excel, PowerPoint, JPG or PNG, up to 10 MB)",
  showVendor = true,
  buttonLabel = "Check document",
  uploadLabel = "Upload document",
  sessionId = null,
  onResultChange,
}: Props) {
  const [file, setFile] = useState<File | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [vendor, setVendor] = useState("");
  const [report, setReport] = useState<DocumentReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [config, setConfig] = useState<Config | null>(null);
  const [plan, setPlan] = useState<PlanStep[]>([]);
  const [stage, setStage] = useState(0);
  const [finished, setFinished] = useState(false);
  const pendingRef = useRef<DocumentReport | null>(null);
  const resultsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch(`${apiBase}/config`)
      .then((r) => (r.ok ? r.json() : null))
      .then((c: Config | null) => setConfig(c))
      .catch(() => setConfig(null));
  }, [apiBase]);

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

  function startOver() {
    setReport(null);
    setVendor("");
    clear();
  }

  function clear() {
    if (inputRef.current) inputRef.current.value = "";
    pick(null);
  }

  async function run() {
    if (!file) return;
    const nextPlan = buildPlan({
      container: !!sessionId || config?.sandbox?.mode === "container",
      ownContainer: !!sessionId,
      model: !!config?.reasoning_enabled,
      local: !!config?.local,
      image: /\.(jpe?g|png)$/i.test(file.name),
    });
    pendingRef.current = null;
    setReport(null);
    setError(null);
    setPlan(nextPlan);
    setStage(0);
    setFinished(false);
    setLoading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      if (vendor.trim()) form.append("vendor", vendor.trim());
      const res = await fetch(`${apiBase}/analyze-document/stream`, {
        method: "POST",
        body: form,
        headers: sessionId ? { "X-Session-Id": sessionId } : undefined,
      });
      if (!res.ok) {
        throw new Error(
          res.status === 413 ? "That file is too large."
          : res.status === 503 ? "The private container is required but is not available."
          : `The check failed (${res.status}).`,
        );
      }
      pendingRef.current = await readStream<DocumentReport>(res, (s) => {
        const index = nextPlan.findIndex((p) => p.key === s);
        if (index >= 0) setStage((current) => Math.max(current, index));
      });
      setFinished(true);
    } catch (e) {
      setError((e as Error).message);
      setLoading(false);
    }
  }

  /** The overlay has finished its last slide and faded out: now the result appears. */
  function onOverlayClosed() {
    setReport(pendingRef.current);
    setLoading(false);
  }

  useEffect(() => {
    onResultChange?.(!!report && !loading);
  }, [report, loading, onResultChange]);

  useEffect(() => {
    if (!report || loading) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    resultsRef.current?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    resultsRef.current?.focus({ preventScroll: true });
  }, [report, loading]);

  return (
    <section aria-labelledby="doc-label">
      {!report && (
        <>
        <h2 id="doc-label" className="text-xs font-semibold uppercase tracking-wide text-zinc-600 dark:text-zinc-300">
          {heading}
        </h2>
        <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-300">{intro}</p>

        <div className="mt-3 flex flex-wrap items-end gap-3">
          <div>
            <p id="doc-file-hint" className="text-sm text-zinc-600 dark:text-zinc-300">
              {fileLabel}
            </p>
            <div className="mt-1 flex flex-wrap items-center gap-3">
              {/* The real input stays in the page (keyboard and screen-reader accessible); the label is the visible button. */}
              <input
                id="doc-file"
                ref={inputRef}
                type="file"
                accept={accept}
                aria-describedby="doc-file-hint"
                onChange={(e) => pick(e.target.files?.[0] ?? null)}
                className="peer sr-only"
              />
              <label
                htmlFor="doc-file"
                className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-zinc-300 px-4 py-2 text-sm font-medium transition hover:bg-zinc-50 peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 dark:border-zinc-700 dark:hover:bg-zinc-900"
              >
                <Upload className="size-4" aria-hidden />
                {file ? "Choose a different file" : uploadLabel}
              </label>
              {file ? (
                <span className="flex min-w-0 items-center gap-2 text-sm">
                  <span className="max-w-[16rem] truncate" title={file.name}>
                    {file.name}
                  </span>
                  <span className="shrink-0 text-zinc-600 dark:text-zinc-300">({formatSize(file.size)})</span>
                  <button
                    type="button"
                    onClick={clear}
                    aria-label={`Remove ${file.name}`}
                    className="shrink-0 rounded p-1 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 hover:text-inherit dark:hover:bg-zinc-800"
                  >
                    <X className="size-4" aria-hidden />
                  </button>
                </span>
              ) : (
                <span className="text-sm text-zinc-600 dark:text-zinc-300">No file chosen</span>
              )}
            </div>
          </div>
          {showVendor && (
          <div>
            <label htmlFor="doc-vendor" className="block text-sm text-zinc-600 dark:text-zinc-300">
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
        </>
      )}

      {report && !loading && (
        <button type="button" onClick={startOver} className="no-print inline-flex items-center gap-2 rounded-lg border border-zinc-300 px-4 py-2 text-sm font-medium transition hover:bg-zinc-100 dark:border-zinc-600 dark:hover:bg-zinc-800">
          <RotateCcw className="size-4" aria-hidden />
          Check another file
        </button>
      )}

      {loading && (
        <AnalysisOverlay
          steps={plan.map(({ label, detail }) => ({ label, detail }))}
          stage={stage}
          finished={finished}
          onClosed={onOverlayClosed}
        />
      )}

      {error && (
        <p className="mt-3 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-900" role="alert">
          {error}
        </p>
      )}

      {report && (
        <div ref={resultsRef} tabIndex={-1} className="mt-6 scroll-mt-4 space-y-4 outline-none">
          <DocumentReportView report={report} />
          <DownloadReport />
        </div>
      )}
    </section>
  );
}

/** Everything found in one document. Also used for an email's attachment. */
export function DocumentReportView({ report, showRisk = true }: { report: DocumentReport; showRisk?: boolean }) {
  return (
    <div className={showRisk ? "grid items-start gap-4 lg:grid-cols-2" : "space-y-4"}>
      <p className="text-xs text-zinc-600 dark:text-zinc-300 lg:col-span-2">
        <strong className="text-inherit">{report.filename || "File"}</strong> · detected as {report.format} ·{" "}
        {formatSize(report.size_bytes)}
        {report.isolation === "container" ? " · opened in a sandbox container" : ""}
        {report.content?.pages ? ` · ${report.content.pages} page(s)` : ""}
      </p>

      {report.risk ? (
        <>
          {showRisk && <div className="lg:col-span-2"><RiskDashboard risk={report.risk} /></div>}
          <p className="text-sm lg:col-span-2" role="status">{report.summary}</p>
        </>
      ) : report.band ? (
        <DecisionBanner band={report.band} summary={report.summary} placeholder={false} />
      ) : (
        <p className="text-sm text-zinc-600 dark:text-zinc-300" role="status">{report.summary}</p>
      )}

      {report.content && report.content.extracted && <DocumentReadingCard content={report.content} />}

      {report.content && report.content.identifiers.length > 0 && <IdentifiersCard items={report.content.identifiers} />}

      {Object.keys(report.fields).length > 0 && (
        <Card title="What the file says about itself">
          <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-2">
            {Object.entries(report.fields).map(([k, v]) => (
              <div key={k}>
                <dt className="text-xs text-zinc-600 dark:text-zinc-300">{k}</dt>
                <dd className="break-words">{v}</dd>
              </div>
            ))}
          </dl>
        </Card>
      )}

      <Card title="What stands out" aside={<span className="text-xs text-zinc-600 dark:text-zinc-300">strongest first</span>}>
        <SignalList signals={report.signals} />
      </Card>

      {report.band && report.band !== "allow" && report.verification_steps.length > 0 && (
        <Card title="Before you pay or reply">
          <Checklist steps={report.verification_steps} />
        </Card>
      )}

      {report.content && report.content.links.length > 0 && (
        <Card title="Links inside the document">
          <ul className="space-y-1 text-sm">
            {report.content.links.map((l) => (
              <li key={l} className="break-all font-mono text-xs">{l}</li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-zinc-600 dark:text-zinc-300">Shown as text only. They were not opened. Do not click them to check.</p>
        </Card>
      )}

      {report.content && report.content.excerpt && (
        <details className="tg-card p-5 text-sm lg:col-span-2">
          <summary className="cursor-pointer font-medium">
            Text we read from the file ({report.content.characters.toLocaleString()} characters
            {report.content.truncated ? ", cut short" : ""})
          </summary>
          <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap break-words text-xs text-zinc-600 dark:text-zinc-400">
            {report.content.excerpt}
          </pre>
        </details>
      )}

      {report.could_not_check.length > 0 && (
        <Card title="What we could not check">
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {report.could_not_check.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-zinc-600 dark:text-zinc-300">Unchecked is not the same as suspicious.</p>
        </Card>
      )}
    </div>
  );
}
