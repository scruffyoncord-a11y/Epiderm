"use client";

import { useEffect, useState } from "react";
import { Card, Checklist, ChecksList, DecisionBanner, HighlightedChat, ReasoningCard, SignalList, TrustBar } from "./components";
import { DocumentCheck } from "./document-check";
import type { Analysis, Config, ScenarioDetail, ScenarioSummary } from "./types";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8001";
const MAX_CHARS = 5000;

async function api<T>(path: string, init?: { method: string; body?: unknown }): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    method: init?.method ?? "GET",
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    body: init?.body ? JSON.stringify(init.body) : undefined,
  });
  if (!res.ok) throw new Error(`${path} returned ${res.status}`);
  return res.json();
}

type Result = {
  analysis: Analysis;
  text: string;
  sender: string;
  action: ScenarioDetail["event"]["action"] | null;
  mode: "example" | "text";
};

export default function Home() {
  const [examples, setExamples] = useState<ScenarioSummary[]>([]);
  const [text, setText] = useState("");
  const [ip, setIp] = useState("");
  const [exampleId, setExampleId] = useState<string | null>(null);
  const [exampleText, setExampleText] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [config, setConfig] = useState<Config | null>(null);

  useEffect(() => {
    api<Config>("/config").then(setConfig).catch(() => setConfig(null));
    api<ScenarioSummary[]>("/scenarios")
      .then(setExamples)
      .catch((e: Error) => setError(`Cannot reach the API at ${API}: ${e.message}`));
  }, []);

  async function loadExample(id: string) {
    setError(null);
    setResult(null);
    try {
      const d = await api<ScenarioDetail>(`/scenarios/${id}`);
      const msg = d.event.evidence.chat?.text ?? "";
      setText(msg);
      setExampleText(msg);
      setExampleId(id);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  function onEdit(value: string) {
    setText(value);
    if (exampleId && value !== exampleText) setExampleId(null); // edited: no longer the saved example
  }

  async function run() {
    if (!text.trim()) return;
    setLoading(true);
    setError(null);
    try {
      if (exampleId) {
        const [d, analysis] = await Promise.all([
          api<ScenarioDetail>(`/scenarios/${exampleId}`),
          api<Analysis>(`/analyze/${exampleId}`, { method: "POST" }),
        ]);
        setResult({
          analysis,
          text: d.event.evidence.chat?.text ?? text,
          sender: d.event.evidence.chat?.sender_claimed ?? "Sender",
          action: d.event.action,
          mode: "example",
        });
      } else {
        const analysis = await api<Analysis>("/analyze-text", { method: "POST", body: { text, ip: ip.trim() || null } });
        setResult({ analysis, text, sender: "Message you entered", action: null, mode: "text" });
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  const a = result?.analysis;
  const current = examples.find((s) => s.id === exampleId);

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-8 sm:px-6">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">TrustGuard</h1>
        <p className="mt-1 text-zinc-500">
          Checks whether the identity, the media and the context agree, and explains why.
        </p>
      </header>

      <section className="mt-6" aria-labelledby="describe-label">
        <h2 id="describe-label" className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
          1. Describe your scenario
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
          onChange={(e) => onEdit(e.target.value)}
          maxLength={MAX_CHARS}
          rows={6}
          placeholder="e.g. Hi, this is Rahul from the CFO office. I'm in a meeting and can't take calls. Please transfer Rs 2,40,000 to this account today and don't tell anyone."
          className="mt-2 w-full rounded-lg border border-zinc-300 bg-transparent p-3 text-sm leading-relaxed dark:border-zinc-700"
        />
        <div className="mt-1 flex justify-between text-xs text-zinc-500">
          <span>{current ? `Loaded example: ${current.title}` : "Custom text"}</span>
          <span>
            {text.length}/{MAX_CHARS}
          </span>
        </div>

        <div className="mt-3">
          <label htmlFor="scenario-ip" className="block text-sm text-zinc-500">
            IP address the message came from (optional)
          </label>
          <input
            id="scenario-ip"
            type="text"
            inputMode="text"
            value={ip}
            onChange={(e) => setIp(e.target.value)}
            maxLength={64}
            placeholder="e.g. 8.8.8.8"
            className="mt-1 w-full max-w-xs rounded-lg border border-zinc-300 bg-transparent p-2 text-sm dark:border-zinc-700"
          />
          <p className="mt-1 text-xs text-zinc-500">
            If given, a reverse DNS lookup is made through this computer&apos;s DNS resolver to see whether it looks like a
            home connection, a cloud server or a VPN. Private and local addresses are never looked up.
          </p>
        </div>

        <div className="mt-4">
          <p className="text-xs text-zinc-500">Or try an example:</p>
          <div className="mt-1 flex flex-wrap gap-2" role="group" aria-label="Examples">
            {examples.map((s) => (
              <button
                key={s.id}
                type="button"
                aria-pressed={exampleId === s.id}
                onClick={() => loadExample(s.id)}
                className={`rounded-full border px-3 py-1 text-xs transition ${
                  exampleId === s.id
                    ? "border-zinc-900 bg-zinc-100 dark:border-zinc-100 dark:bg-zinc-800"
                    : "border-zinc-300 hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-900"
                }`}
              >
                {s.title}
              </button>
            ))}
          </div>
          {current && <p className="mt-2 text-sm text-zinc-500">{current.description}</p>}
        </div>

        <button
          type="button"
          onClick={run}
          disabled={!text.trim() || loading}
          className="mt-4 rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-40 dark:bg-zinc-100 dark:text-zinc-900"
        >
          {loading ? "Analysing…" : "Analyse"}
        </button>
        {loading && !exampleId && config?.reasoning_enabled && (
          <p className="mt-2 text-sm text-zinc-500" role="status">
            {config.local ? "The local model is reading your text. This can take a minute or more." : "The reasoning model is reading your text. This usually takes a few seconds."}
          </p>
        )}
      </section>

      <DocumentCheck apiBase={API} />

      {error && (
        <p className="mt-4 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-900" role="alert">
          {error}
        </p>
      )}

      {result && a && (
        <div className="mt-6 space-y-4">
          <p className="text-xs text-zinc-500">
            {result.mode === "example"
              ? "Full example with simulated device, IP and location data. Results are placeholders until the engine is finished."
              : "Text-only check: a real rule-based review of the wording. Device, IP, location, links and documents were not checked."}
          </p>

          {result.mode === "text" && a.reasoning && <ReasoningCard r={a.reasoning} />}

          <DecisionBanner band={a.band} summary={a.summary} placeholder={a.is_placeholder} />

          {result.action && (
            <p className="text-sm text-zinc-500">
              Requested action: <strong className="text-inherit">{result.action.type}</strong>
              {result.action.amount != null && <> of Rs {result.action.amount.toLocaleString("en-IN")}</>}
              {result.action.payee && <> to {result.action.payee}</>}
            </p>
          )}

          <Card title="Trust score">
            <TrustBar score={a.trust_score} low={a.trust_low} high={a.trust_high} required={a.required_trust} />
          </Card>

          {a.checks.length > 0 && (
            <Card title="Do the pieces agree?">
              <ChecksList checks={a.checks} />
            </Card>
          )}

          <Card title="What drove the result" aside={<span className="text-xs text-zinc-500">strongest first</span>}>
            <SignalList signals={a.signals} />
          </Card>

          <Card title="Message analysed">
            <HighlightedChat sender={result.sender} text={result.text} signals={a.signals} />
          </Card>

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
              Example session data (IP, device, location) is simulated. In real use TrustGuard would keep only hashes and
              summaries, ask consent before enrolling a face or voice, and delete uploads after the session.
            </p>
          </Card>
        </div>
      )}
    </main>
  );
}
