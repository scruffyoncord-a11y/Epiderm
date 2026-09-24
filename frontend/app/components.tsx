"use client";

import { useState } from "react";
import type { Band, Check, CheckResult, Direction, Reasoning, Signal } from "./types";

const BAND: Record<Band, { label: string; headline: string; box: string; chip: string }> = {
  allow: {
    label: "Allow",
    headline: "Consistent with this user's normal pattern",
    box: "border-emerald-300 bg-emerald-50 text-emerald-950 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-100",
    chip: "bg-emerald-600 text-white",
  },
  step_up: {
    label: "Step-up check",
    headline: "One extra check needed before this goes ahead",
    box: "border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-100",
    chip: "bg-amber-600 text-white",
  },
  verify: {
    label: "Verification required",
    headline: "Hold this action and verify independently",
    box: "border-red-300 bg-red-50 text-red-950 dark:border-red-800 dark:bg-red-950/40 dark:text-red-100",
    chip: "bg-red-600 text-white",
  },
};

export function Card({ title, children, aside }: { title: string; children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">{title}</h2>
        {aside}
      </div>
      <div className="mt-3">{children}</div>
    </section>
  );
}

export function DecisionBanner({ band, summary, placeholder }: { band: Band; summary: string; placeholder: boolean }) {
  const b = BAND[band];
  return (
    <div className={`rounded-lg border p-4 ${b.box}`} role="status">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded px-2 py-0.5 text-xs font-semibold ${b.chip}`}>{b.label}</span>
        {placeholder && (
          <span className="rounded border border-current px-2 py-0.5 text-xs opacity-80">placeholder result</span>
        )}
      </div>
      <p className="mt-2 text-lg font-semibold">{b.headline}</p>
      <p className="mt-1 text-sm opacity-90">{summary}</p>
      <p className="mt-2 text-xs opacity-70">
        This is a risk assessment, not proof. A person makes the final decision.
      </p>
    </div>
  );
}

export function TrustBar({ score, low, high, required }: { score: number; low: number; high: number; required: number }) {
  return (
    <div>
      <div className="flex justify-between text-sm">
        <span>
          Trust score <strong>{score}</strong>{" "}
          <span className="text-zinc-500">(range {low}-{high})</span>
        </span>
        <span className="text-zinc-500">Needed for this action: {required}</span>
      </div>
      <div
        className="relative mt-2 h-4 rounded bg-zinc-200 dark:bg-zinc-800"
        role="img"
        aria-label={`Trust score ${score} out of 100, range ${low} to ${high}, required ${required}`}
      >
        <div className="absolute inset-y-0 rounded bg-zinc-400/60 dark:bg-zinc-500/60" style={{ left: `${low}%`, width: `${Math.max(high - low, 1)}%` }} />
        <div className="absolute -inset-y-1 w-1 rounded bg-zinc-900 dark:bg-zinc-100" style={{ left: `calc(${score}% - 2px)` }} title="Score" />
        <div className="absolute -inset-y-1 w-0.5 bg-red-600" style={{ left: `${required}%` }} title="Required" />
      </div>
      <div className="mt-1 flex gap-4 text-xs text-zinc-500">
        <span>Dark marker: score</span>
        <span>Grey band: uncertainty</span>
        <span>Red line: required</span>
      </div>
    </div>
  );
}

const CHECK_STYLE: Record<CheckResult, { text: string; cls: string }> = {
  consistent: { text: "Consistent", cls: "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/50 dark:text-emerald-100" },
  inconsistent: { text: "Inconsistent", cls: "bg-red-100 text-red-900 dark:bg-red-900/50 dark:text-red-100" },
  cannot_verify: { text: "Cannot verify", cls: "bg-zinc-200 text-zinc-800 dark:bg-zinc-800 dark:text-zinc-200" },
};

export function ChecksList({ checks }: { checks: Check[] }) {
  return (
    <ul className="divide-y divide-zinc-200 dark:divide-zinc-800">
      {checks.map((c) => (
        <li key={c.id} className="flex items-start justify-between gap-3 py-2 text-sm">
          <div>
            <p>{c.label}</p>
            {c.detail && <p className="text-xs text-zinc-500">{c.detail}</p>}
          </div>
          <span className={`shrink-0 rounded px-2 py-0.5 text-xs font-medium ${CHECK_STYLE[c.result].cls}`}>
            {CHECK_STYLE[c.result].text}
          </span>
        </li>
      ))}
    </ul>
  );
}

const DIR: Record<Direction, { text: string; badge: string; bar: string }> = {
  suspicious: { text: "Raises risk", badge: "bg-red-100 text-red-900 dark:bg-red-900/50 dark:text-red-100", bar: "bg-red-500" },
  reassuring: { text: "Reassuring", badge: "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/50 dark:text-emerald-100", bar: "bg-emerald-500" },
  neutral: { text: "Neutral", badge: "bg-zinc-200 text-zinc-800 dark:bg-zinc-800 dark:text-zinc-200", bar: "bg-zinc-400" },
  unknown: { text: "Unknown", badge: "bg-zinc-200 text-zinc-800 dark:bg-zinc-800 dark:text-zinc-200", bar: "bg-zinc-400" },
};

export function SignalList({ signals }: { signals: Signal[] }) {
  const sorted = [...signals].sort((a, b) => b.strength * b.confidence - a.strength * a.confidence);
  return (
    <ul className="space-y-3">
      {sorted.map((s) => {
        const weight = Math.round(s.strength * s.confidence * 100);
        return (
          <li key={s.id}>
            <div className="flex items-start justify-between gap-3">
              <p className="text-sm font-medium">{s.finding}</p>
              <span className={`shrink-0 rounded px-2 py-0.5 text-xs font-medium ${DIR[s.direction].badge}`}>
                {DIR[s.direction].text}
              </span>
            </div>
            <div className="mt-1 flex items-center gap-2">
              <div className="h-1.5 w-full rounded bg-zinc-200 dark:bg-zinc-800" aria-hidden>
                <div className={`h-full rounded ${DIR[s.direction].bar}`} style={{ width: `${weight}%` }} />
              </div>
              <span className="w-24 shrink-0 text-right text-xs text-zinc-500">weight {weight}</span>
            </div>
            {s.evidence && <p className="mt-0.5 text-xs text-zinc-500">{s.category}: {s.evidence}</p>}
          </li>
        );
      })}
    </ul>
  );
}

export function HighlightedChat({ sender, text, signals }: { sender: string; text: string; signals: Signal[] }) {
  const spans = signals
    .flatMap((s) => s.spans)
    .sort((a, b) => a[0] - b[0]);
  const parts: React.ReactNode[] = [];
  let pos = 0;
  spans.forEach(([start, end], i) => {
    if (start < pos) return; // skip overlaps
    if (start > pos) parts.push(text.slice(pos, start));
    parts.push(
      <mark key={i} className="rounded bg-red-200 px-0.5 text-red-950 dark:bg-red-900/60 dark:text-red-50">
        {text.slice(start, end)}
      </mark>,
    );
    pos = end;
  });
  parts.push(text.slice(pos));
  return (
    <div>
      <p className="text-xs text-zinc-500">From: {sender}</p>
      <p className="mt-1 rounded bg-zinc-100 p-3 text-sm leading-relaxed dark:bg-zinc-900">{parts}</p>
      <p className="mt-1 text-xs text-zinc-500">Highlighted phrases are the wording that raised risk.</p>
    </div>
  );
}

export function Checklist({ steps }: { steps: string[] }) {
  const [done, setDone] = useState<boolean[]>(() => steps.map(() => false));
  const count = done.filter(Boolean).length;
  return (
    <div>
      <ul className="space-y-2">
        {steps.map((step, i) => (
          <li key={i}>
            <label className="flex cursor-pointer items-start gap-2 text-sm">
              <input
                type="checkbox"
                className="mt-1"
                checked={done[i]}
                onChange={() => setDone((d) => d.map((v, j) => (j === i ? !v : v)))}
              />
              <span className={done[i] ? "text-zinc-500 line-through" : ""}>{step}</span>
            </label>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-sm text-zinc-500" aria-live="polite">
        {count} of {steps.length} checks done.
        {count === steps.length && " Checks complete. The decision to proceed is yours."}
      </p>
    </div>
  );
}

const CONCERN: Record<string, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
};

export function ReasoningCard({ r }: { r: Reasoning }) {
  if (r.status !== "used") {
    return (
      <Card title="Reasoning model">
        <p className="text-sm" role="status">
          <strong>{r.status === "unavailable" ? "Not running." : "Could not be used."}</strong> {r.note}
        </p>
      </Card>
    );
  }
  return (
    <Card title="Reasoning model" aside={<span className="text-xs text-zinc-500">read first · {r.model}{r.local ? " · on this computer" : ""}</span>}>
      <p className="text-sm leading-relaxed">{r.summary}</p>
      <dl className="mt-3 grid gap-x-4 gap-y-1 text-sm sm:grid-cols-2">
        {r.claimed_identity && (
          <div>
            <dt className="text-xs text-zinc-500">Sender claims to be</dt>
            <dd>{r.claimed_identity}</dd>
          </div>
        )}
        {r.request_type && (
          <div>
            <dt className="text-xs text-zinc-500">What is being asked</dt>
            <dd>{r.request_type.replace(/_/g, " ")}</dd>
          </div>
        )}
        {r.concern && (
          <div>
            <dt className="text-xs text-zinc-500">Model&apos;s concern (advisory)</dt>
            <dd>{CONCERN[r.concern]}</dd>
          </div>
        )}
      </dl>
      {r.inconsistencies.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-semibold text-zinc-500">Does not add up</p>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
            {r.inconsistencies.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        </div>
      )}
      {r.innocent_explanations.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-semibold text-zinc-500">Genuine explanations to consider</p>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
            {r.innocent_explanations.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        </div>
      )}
      <p className="mt-3 text-xs text-zinc-500">{r.note}</p>
    </Card>
  );
}
