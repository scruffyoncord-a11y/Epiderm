"use client";

import { Paperclip, RotateCcw, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  Card, Checklist, ChecksList, DecisionBanner, FollowUpCard, HeaderCard, HighlightedChat, OfficialContactCard, ReasoningCard, SignalList,
} from "./components";
import { AnalysisOverlay } from "./analysis-overlay";
import { DocumentReportView } from "./document-check";
import { DownloadReport } from "./download-report";
import { API, readStream } from "./lib";
import { RiskDashboard } from "./risk-dashboard";
import type { Config, EmailResult } from "./types";

const MAX_CHARS = 5000;
const MAX_FILE_BYTES = 10 * 1024 * 1024;
const ATTACH_ACCEPT = ".pdf,.docx,.xlsx,.pptx,.jpg,.jpeg,.png";

async function api<T>(path: string, init?: { method: string; body?: unknown; sessionId?: string | null }): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    method: init?.method ?? "GET",
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.sessionId ? { "X-Session-Id": init.sessionId } : {}),
    },
    body: init?.body ? JSON.stringify(init.body) : undefined,
  });
  if (!res.ok) throw new Error(`${path} returned ${res.status}`);
  return res.json();
}

type Result = {
  email: EmailResult;
  text: string;
  sender: string;
};

type Stage =
  | "started" | "container" | "reading" | "verifying"
  | "attachment" | "attachment_container" | "attachment_reading" | "attachment_verifying";
type PlanStep = { key: Stage; label: string; detail: string; also?: Stage[] };

/** The steps this particular check will really go through. Each maps to a stage the server reports. */
function buildPlan(o: {
  message: boolean; container: boolean; ownContainer: boolean; model: boolean; local: boolean;
  attachment: boolean; sandbox: boolean; image: boolean;
}): PlanStep[] {
  const plan: PlanStep[] = [{ key: "started", label: "Request received", detail: "Your check is on its way" }];
  if (o.message) plan.push(...messageSteps(o));
  if (o.attachment) {
    plan.push({
      key: "attachment",
      also: ["attachment_container"],
      label: "Opening the attachment",
      detail: o.sandbox ? "Inside a private container with no network" : "Read in memory, never stored",
    });
    if (o.model) {
      plan.push({
        key: "attachment_reading",
        label: o.image ? "Reading the attached image" : "Reading the attachment",
        detail: o.local ? "A model on this computer is reading it" : "The reasoning model is reading it",
      });
    }
    plan.push({ key: "attachment_verifying", label: "Checking the attachment", detail: "Numbers, dates, payee and metadata" });
  }
  return plan;
}

function messageSteps(o: { container: boolean; ownContainer: boolean; model: boolean; local: boolean }): PlanStep[] {
  const plan: PlanStep[] = [];
  if (o.container) {
    plan.push({
      key: "container",
      label: o.ownContainer ? "Reading headers in your container" : "Opening a private container",
      detail: "No network, and deleted afterwards",
    });
  }
  if (o.model) {
    plan.push({
      key: "reading",
      label: "Reading the context",
      detail: o.local ? "A model on this computer is reading your text" : "The reasoning model is reading your text",
    });
  }
  plan.push({ key: "verifying", label: "Verifying the evidence", detail: "Running the rules and the sender checks" });
  return plan;
}

function formatSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function PhishingCheck({ sessionId, onResultChange }: { sessionId: string | null; onResultChange?: (has: boolean) => void }) {
  const [text, setText] = useState("");
  const [headers, setHeaders] = useState("");
  const [email, setEmail] = useState("");
  const [org, setOrg] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [config, setConfig] = useState<Config | null>(null);
  const [running, setRunning] = useState(false);
  const [plan, setPlan] = useState<PlanStep[]>([]);
  const [stage, setStage] = useState(0);
  const [finished, setFinished] = useState(false);
  const pendingRef = useRef<Result | null>(null);
  const resultsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api<Config>("/config")
      .then(setConfig)
      .catch(() => setError(`Cannot reach the API at ${API}. Is the backend running?`));
  }, []);

  /** Runs the check and follows the server's real progress; the result is held until the overlay has finished. */
  function startOver() {
    setResult(null);
    setText("");
    setHeaders("");
    setEmail("");
    setOrg("");
    pickFile(null);
  }

  function pickFile(f: File | null) {
    setError(null);
    if (f && f.size > MAX_FILE_BYTES) {
      setError("That attachment is larger than 10 MB.");
      f = null;
    }
    setFile(f);
    if (!f && fileRef.current) fileRef.current.value = "";
  }

  async function run(over?: { email?: string; org?: string }) {
    if (!text.trim() && !headers.trim() && !file) return;
    if (over?.email !== undefined) setEmail(over.email);
    if (over?.org !== undefined) setOrg(over.org);
    const sandboxed = !!sessionId || config?.sandbox?.mode === "container";
    const nextPlan = buildPlan({
      message: !!text.trim() || !!headers.trim(),
      container: !!headers.trim() && sandboxed,
      ownContainer: !!sessionId,
      model: !!config?.reasoning_enabled,
      local: !!config?.local,
      attachment: !!file,
      sandbox: sandboxed,
      image: !!file && /\.(jpe?g|png)$/i.test(file.name),
    });
    if (!text.trim()) {
      const i = nextPlan.findIndex((p) => p.key === "reading");
      if (i >= 0) nextPlan.splice(i, 1);  // the model only reads the message when there is message text
    }
    pendingRef.current = null;
    setResult(null);
    setError(null);
    setPlan(nextPlan);
    setStage(0);
    setFinished(false);
    setRunning(true);
    try {
      const form = new FormData();
      form.append("text", text);
      if (headers.trim()) form.append("headers", headers.trim());
      const senderEmail = (over?.email ?? email).trim();
      const organisation = (over?.org ?? org).trim();
      if (senderEmail) form.append("sender_email", senderEmail);
      if (organisation) form.append("organisation", organisation);
      if (file) form.append("file", file);
      const res = await fetch(`${API}/analyze-email/stream`, {
        method: "POST",
        headers: sessionId ? { "X-Session-Id": sessionId } : undefined,
        body: form,
      });
      if (!res.ok) {
        throw new Error(
          res.status === 503 ? "The private container is required but is not available."
          : res.status === 413 ? "That attachment is too large."
          : `The check failed (${res.status}).`,
        );
      }
      const checked = await readStream<EmailResult>(res, (s) => {
        const index = nextPlan.findIndex((p) => p.key === s || p.also?.includes(s as Stage));
        if (index >= 0) setStage((current) => Math.max(current, index));
      });
      pendingRef.current = { email: checked, text, sender: "Message you entered" };
      setFinished(true);
    } catch (e) {
      setError((e as Error).message);
      setRunning(false);
    }
  }

  /** The overlay has finished its last slide and faded out: now the result appears. */
  function onOverlayClosed() {
    setResult(pendingRef.current);
    setRunning(false);
  }

  useEffect(() => {
    onResultChange?.(!!result && !running);
  }, [result, running, onResultChange]);

  // After the result appears, bring it into view (smoothly, unless the person asked for less motion).
  useEffect(() => {
    if (!result || running) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    resultsRef.current?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    resultsRef.current?.focus({ preventScroll: true });
  }, [result, running]);

  const a = result?.email.message ?? null;
  const attachment = result?.email.attachment ?? null;
  const risk = result?.email.risk ?? null;

  return (
    <div>
      {!result && (
        <section aria-labelledby="describe-label" className="max-w-5xl">
          <h2 id="describe-label" className="text-xs font-semibold uppercase tracking-wide text-zinc-600 dark:text-zinc-300">
            Describe what you received
          </h2>
          <label htmlFor="scenario-text" className="mt-2 block text-sm text-zinc-600 dark:text-zinc-300">
            Paste the message you received, or write what happened.{" "}
            {config?.reasoning_enabled
              ? config.local
                ? `A model running on this computer (${config.model}) reads it first, then transparent rules check it. Your text does not leave this machine. This can take a minute or more on this hardware.`
                : `Your text is sent to ${config.provider === "gemini" ? "Google's Gemini API" : "Anthropic's API"} (${config.model}) to be read first, then checked by transparent rules. It is not processed only on this computer.`
              : "No reasoning model is available, so only the rule-based wording check runs and your text stays on this app's server."}
          </label>
          <textarea
            id="scenario-text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            maxLength={MAX_CHARS}
            rows={6}
            placeholder="e.g. Hi, this is Rahul from the CFO office. I'm in a meeting and can't take calls. Please transfer Rs 2,40,000 to this account today and don't tell anyone."
            className="mt-2 w-full rounded-lg border border-zinc-300 bg-transparent p-3 text-sm leading-relaxed dark:border-zinc-700"
          />
          <div className="mt-1 flex justify-end text-xs text-zinc-600 dark:text-zinc-300">
            <span>
              {text.length}/{MAX_CHARS}
            </span>
          </div>

          <div className="mt-3">
            <label htmlFor="scenario-headers" className="block text-sm text-zinc-600 dark:text-zinc-300">
              Email headers (optional, the best evidence for an email)
            </label>
            <details className="mt-1 text-xs text-zinc-600 dark:text-zinc-300">
              <summary className="cursor-pointer">How to get them</summary>
              <ol className="mt-1 list-decimal space-y-0.5 pl-5">
                <li>Gmail: open the email, click the three-dot menu, choose <strong>Show original</strong>.</li>
                <li>Copy the top table (SPF, DKIM, DMARC) or the whole text, and paste it below.</li>
                <li>Outlook: File, Properties, Internet headers. Yahoo: More, View raw message.</li>
              </ol>
            </details>
            <textarea
              id="scenario-headers"
              value={headers}
              onChange={(e) => setHeaders(e.target.value)}
              maxLength={60000}
              rows={4}
              placeholder="Paste the headers here"
              className="mt-1 w-full rounded-lg border border-zinc-300 bg-transparent p-2 font-mono text-xs dark:border-zinc-700"
            />
            <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-300">
              Read by this app&apos;s own code, not sent to the AI model. We keep only the sender, reply-to, SPF/DKIM/DMARC
              results and the sending server, whose address is found for you; your own address and the rest are discarded. You can leave the message box empty.
            </p>
          </div>

          <div className="mt-3 flex flex-wrap gap-4">
            <div>
              <label htmlFor="scenario-email" className="block text-sm text-zinc-600 dark:text-zinc-300">
                Sender&apos;s email address (optional)
              </label>
              <input
                id="scenario-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                maxLength={254}
                placeholder="e.g. support@gmail.com"
                className="mt-1 w-full max-w-xs rounded-lg border border-zinc-300 bg-transparent p-2 text-sm dark:border-zinc-700"
              />
            </div>
            <div>
              <label htmlFor="scenario-org" className="block text-sm text-zinc-600 dark:text-zinc-300">
                Company they claim to be from (optional)
              </label>
              <input
                id="scenario-org"
                type="text"
                value={org}
                onChange={(e) => setOrg(e.target.value)}
                maxLength={120}
                placeholder="e.g. Acme Corp"
                className="mt-1 w-full max-w-xs rounded-lg border border-zinc-300 bg-transparent p-2 text-sm dark:border-zinc-700"
              />
            </div>
          </div>
          <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-300">
            If the message came from a Gmail or other free address, give it here. Epiderm compares it with the official
            email domains on record for the company.
          </p>

          <div className="mt-4">
            <p id="attach-hint" className="text-sm text-zinc-600 dark:text-zinc-300">
              Attachment (optional): the invoice, letter or image that came with the email. It is checked with the same document
              pipeline and combined into one score.
            </p>
            <div className="mt-1 flex flex-wrap items-center gap-3">
              <input
                id="attach-file"
                ref={fileRef}
                type="file"
                accept={ATTACH_ACCEPT}
                aria-describedby="attach-hint"
                onChange={(e) => pickFile(e.target.files?.[0] ?? null)}
                className="peer sr-only"
              />
              <label
                htmlFor="attach-file"
                className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-zinc-300 px-4 py-2 text-sm font-medium transition hover:bg-zinc-50 peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 dark:border-zinc-700 dark:hover:bg-zinc-900"
              >
                <Paperclip className="size-4" aria-hidden />
                {file ? "Choose a different file" : "Attach a document"}
              </label>
              {file ? (
                <span className="flex min-w-0 items-center gap-2 text-sm">
                  <span className="max-w-[16rem] truncate" title={file.name}>{file.name}</span>
                  <span className="shrink-0 text-zinc-600 dark:text-zinc-300">({formatSize(file.size)})</span>
                  <button
                    type="button"
                    onClick={() => pickFile(null)}
                    aria-label={`Remove ${file.name}`}
                    className="shrink-0 rounded p-1 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 hover:text-inherit dark:hover:bg-zinc-800"
                  >
                    <X className="size-4" aria-hidden />
                  </button>
                </span>
              ) : (
                <span className="text-sm text-zinc-600 dark:text-zinc-300">No attachment</span>
              )}
            </div>
          </div>

          <button
            type="button"
            onClick={() => run()}
            disabled={(!text.trim() && !headers.trim() && !file) || running}
            className="mt-4 rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-40 dark:bg-zinc-100 dark:text-zinc-900"
          >
            {running ? "Analysing…" : "Analyse"}
          </button>
        </section>
      )}

      {result && !running && (
        <button type="button" onClick={startOver} className="no-print inline-flex items-center gap-2 rounded-lg border border-zinc-300 px-4 py-2 text-sm font-medium transition hover:bg-zinc-100 dark:border-zinc-600 dark:hover:bg-zinc-800">
          <RotateCcw className="size-4" aria-hidden />
          Check another message
        </button>
      )}

      {running && (
        <AnalysisOverlay
          steps={plan.map(({ label, detail }) => ({ label, detail }))}
          stage={stage}
          finished={finished}
          onClosed={onOverlayClosed}
        />
      )}

      {error && (
        <p className="mt-4 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-900" role="alert">
          {error}
        </p>
      )}

      {result && (
        <div ref={resultsRef} tabIndex={-1} className="mt-6 scroll-mt-4 space-y-4 outline-none">
          <p className="text-xs text-zinc-600 dark:text-zinc-300">
            Checked: {[a && "the wording", a && "the email headers and sender address if you gave them", attachment && "the attachment"]
              .filter(Boolean).join(", ")}. Not checked: links, and the person&apos;s device or location.
          </p>

          {risk && <RiskDashboard risk={risk} />}
        </div>
      )}

      <div className={attachment ? "mt-4 grid items-start gap-8 lg:grid-cols-2" : ""}>
      {result && a && (
        <div className="mt-4 space-y-4">
          {attachment && <h3 className="pt-2 text-lg font-semibold">The message</h3>}

          {a.reasoning && <ReasoningCard r={a.reasoning} />}

          {risk ? (
            <p className="text-sm" role="status">{a.summary}</p>
          ) : (
            <DecisionBanner band={a.band} summary={a.summary} placeholder={a.is_placeholder} />
          )}

          {a.follow_ups.length > 0 && (
            <FollowUpCard items={a.follow_ups} busy={running} onSubmit={(v) => run(v)} />
          )}

          {a.header_summary && <HeaderCard h={a.header_summary} isolation={a.isolation} />}

          {a.checks.length > 0 && (
            <Card title="Do the pieces agree?">
              <ChecksList checks={a.checks} />
            </Card>
          )}

          {a.official_contact && <OfficialContactCard c={a.official_contact} />}

          <Card title="What drove the result" aside={<span className="text-xs text-zinc-600 dark:text-zinc-300">strongest first</span>}>
            <SignalList signals={a.signals} />
          </Card>

          {result.text.trim() && (
            <Card title="Message analysed">
              <HighlightedChat sender={result.sender} text={result.text} signals={a.signals} />
            </Card>
          )}

          {a.could_not_check.length > 0 && (
            <Card title="What we could not check">
              <ul className="list-disc space-y-1 pl-5 text-sm">
                {a.could_not_check.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-zinc-600 dark:text-zinc-300">Unchecked is not the same as suspicious. It widens the score range.</p>
            </Card>
          )}

          {a.verification_steps.length > 0 && (
            <Card title="Verify independently">
              <Checklist key={a.verification_steps.join("|")} steps={a.verification_steps} />
            </Card>
          )}

        </div>
      )}

      {result && attachment && (
        <div className="mt-6 space-y-4">
          <h3 className="text-lg font-semibold">The attachment</h3>
          <DocumentReportView report={attachment} showRisk={false} />
        </div>
      )}
      </div>

      {result && (
        <div className="mt-4 space-y-4">
          <DownloadReport />
          <Card title="Privacy">
            <p className="text-sm text-zinc-600 dark:text-zinc-300">
              Nothing you paste is saved to disk. The app keeps a short-lived copy of the model&apos;s reading in memory so a
              re-check is quick, and it disappears when the server restarts. Email headers are read by this app&apos;s own code,
              and only the fields shown above are kept on screen.
            </p>
          </Card>
        </div>
      )}
    </div>
  );
}
