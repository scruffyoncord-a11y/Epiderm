"use client";

import { useEffect, useRef, useState } from "react";
import {
  Card, Checklist, ChecksList, DecisionBanner, FollowUpCard, HeaderCard, HighlightedChat, OfficialContactCard, ReasoningCard, SignalList, TrustBar,
} from "./components";
import { AnalysisOverlay } from "./analysis-overlay";
import { API } from "./lib";
import type { Analysis, Config } from "./types";

const MAX_CHARS = 5000;

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
  analysis: Analysis;
  text: string;
  sender: string;
};

type Stage = "started" | "container" | "reading" | "verifying";
type StreamEvent =
  | { stage: Stage }
  | { stage: "done"; result: Analysis }
  | { stage: "error"; detail: string };
type PlanStep = { key: Stage; label: string; detail: string };

/** The steps this particular check will really go through. Each maps to a stage the server reports. */
function buildPlan(o: { container: boolean; ownContainer: boolean; model: boolean; local: boolean }): PlanStep[] {
  const plan: PlanStep[] = [{ key: "started", label: "Request received", detail: "Your check is on its way" }];
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

export function PhishingCheck({ sessionId }: { sessionId: string | null }) {
  const [text, setText] = useState("");
  const [headers, setHeaders] = useState("");
  const [email, setEmail] = useState("");
  const [org, setOrg] = useState("");
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
  async function run(over?: { email?: string; org?: string }) {
    if (!text.trim() && !headers.trim()) return;
    if (over?.email !== undefined) setEmail(over.email);
    if (over?.org !== undefined) setOrg(over.org);
    const nextPlan = buildPlan({
      container: !!headers.trim() && (!!sessionId || config?.sandbox?.mode === "container"),
      ownContainer: !!sessionId,
      model: !!text.trim() && !!config?.reasoning_enabled,
      local: !!config?.local,
    });
    pendingRef.current = null;
    setResult(null);
    setError(null);
    setPlan(nextPlan);
    setStage(0);
    setFinished(false);
    setRunning(true);
    try {
      const res = await fetch(`${API}/analyze-text/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(sessionId ? { "X-Session-Id": sessionId } : {}) },
        body: JSON.stringify({
          text,
          headers: headers.trim() || null,
          sender_email: (over?.email ?? email).trim() || null,
          organisation: (over?.org ?? org).trim() || null,
        }),
      });
      if (!res.ok || !res.body) {
        throw new Error(res.status === 503 ? "The private container is required but is not available." : `The check failed (${res.status}).`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let gotResult = false;
      let streamDone = false;
      while (!streamDone) {
        const chunk = await reader.read();
        streamDone = chunk.done;
        buffer += decoder.decode(chunk.value, { stream: !chunk.done });
        let newline = buffer.indexOf("\n");
        while (newline >= 0) {
          const line = buffer.slice(0, newline).trim();
          buffer = buffer.slice(newline + 1);
          newline = buffer.indexOf("\n");
          if (!line) continue;
          const event = JSON.parse(line) as StreamEvent;
          if (event.stage === "error") throw new Error(event.detail);
          if (event.stage === "done") {
            pendingRef.current = { analysis: event.result, text, sender: "Message you entered" };
            gotResult = true;
            setFinished(true);
          } else {
            const index = nextPlan.findIndex((p) => p.key === event.stage);
            if (index >= 0) setStage((current) => Math.max(current, index));
          }
        }
      }
      if (!gotResult) throw new Error("The check ended without a result.");
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

  // After the result appears, bring it into view (smoothly, unless the person asked for less motion).
  useEffect(() => {
    if (!result || running) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    resultsRef.current?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    resultsRef.current?.focus({ preventScroll: true });
  }, [result, running]);

  const a = result?.analysis;

  return (
    <div>
      <section aria-labelledby="describe-label">
        <h2 id="describe-label" className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
          Describe what you received
        </h2>
        <label htmlFor="scenario-text" className="mt-2 block text-sm text-zinc-500">
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
        <div className="mt-1 flex justify-end text-xs text-zinc-500">
          <span>
            {text.length}/{MAX_CHARS}
          </span>
        </div>

        <div className="mt-3">
          <label htmlFor="scenario-headers" className="block text-sm text-zinc-500">
            Email headers (optional, the best evidence for an email)
          </label>
          <details className="mt-1 text-xs text-zinc-500">
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
          <p className="mt-1 text-xs text-zinc-500">
            Read by this app&apos;s own code, not sent to the AI model. We keep only the sender, reply-to, SPF/DKIM/DMARC
            results and the sending server, whose address is found for you; your own address and the rest are discarded. You can leave the message box empty.
          </p>
        </div>

        <div className="mt-3 flex flex-wrap gap-4">
          <div>
            <label htmlFor="scenario-email" className="block text-sm text-zinc-500">
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
            <label htmlFor="scenario-org" className="block text-sm text-zinc-500">
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
        <p className="mt-1 text-xs text-zinc-500">
          If the message came from a Gmail or other free address, give it here. TrustGuard compares it with the official
          email domains on record for the company.
        </p>

        <button
          type="button"
          onClick={() => run()}
          disabled={(!text.trim() && !headers.trim()) || running}
          className="mt-4 rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-40 dark:bg-zinc-100 dark:text-zinc-900"
        >
          {running ? "Analysing…" : "Analyse"}
        </button>
      </section>

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

      {result && a && (
        <div ref={resultsRef} tabIndex={-1} className="mt-6 scroll-mt-4 space-y-4 outline-none">
          <p className="text-xs text-zinc-500">
            Checked: the wording, and the email headers and sender address if you gave them. Not checked: links,
            attachments, and the person&apos;s device or location.
          </p>

          {a.reasoning && <ReasoningCard r={a.reasoning} />}

          <DecisionBanner band={a.band} summary={a.summary} placeholder={a.is_placeholder} />

          {a.follow_ups.length > 0 && (
            <FollowUpCard items={a.follow_ups} busy={running} onSubmit={(v) => run(v)} />
          )}

          {a.header_summary && <HeaderCard h={a.header_summary} isolation={a.isolation} />}

          <Card title="Trust score">
            <TrustBar score={a.trust_score} low={a.trust_low} high={a.trust_high} required={a.required_trust} />
          </Card>

          {a.checks.length > 0 && (
            <Card title="Do the pieces agree?">
              <ChecksList checks={a.checks} />
            </Card>
          )}

          {a.official_contact && <OfficialContactCard c={a.official_contact} />}

          <Card title="What drove the result" aside={<span className="text-xs text-zinc-500">strongest first</span>}>
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
              <p className="mt-2 text-xs text-zinc-500">Unchecked is not the same as suspicious. It widens the score range.</p>
            </Card>
          )}

          {a.verification_steps.length > 0 && (
            <Card title="Verify independently">
              <Checklist key={a.verification_steps.join("|")} steps={a.verification_steps} />
            </Card>
          )}

          <Card title="Privacy">
            <p className="text-sm text-zinc-500">
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
