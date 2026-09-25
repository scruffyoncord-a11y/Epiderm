"use client";

import { useState } from "react";
import type { Band, Check, CheckResult, ContentReport, Direction, FollowUp, HeaderSummary, Identifier, OfficialContact, Reasoning, Signal } from "./types";

const BAND: Record<Band, { label: string; headline: string; box: string; chip: string }> = {
  allow: {
    label: "Allow",
    headline: "Nothing unusual found",
    box: "border-emerald-300 bg-emerald-50 text-emerald-950 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-100",
    chip: "bg-emerald-600 text-white",
  },
  step_up: {
    label: "Step-up check",
    headline: "Take a second look before you act",
    box: "border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-100",
    chip: "bg-amber-600 text-white",
  },
  verify: {
    label: "Verification required",
    headline: "Hold this and verify independently",
    box: "border-red-300 bg-red-50 text-red-950 dark:border-red-800 dark:bg-red-950/40 dark:text-red-100",
    chip: "bg-red-600 text-white",
  },
};

export function Card({ title, children, aside }: { title: string; children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <section className="tg-card p-5">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-zinc-600 dark:text-zinc-300">{title}</h2>
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
          <span className="text-zinc-600 dark:text-zinc-300">(range {low}-{high})</span>
        </span>
        <span className="text-zinc-600 dark:text-zinc-300">Needed for this action: {required}</span>
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
      <div className="mt-1 flex gap-4 text-xs text-zinc-600 dark:text-zinc-300">
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
            {c.detail && <p className="text-xs text-zinc-600 dark:text-zinc-300">{c.detail}</p>}
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
              <span className="w-24 shrink-0 text-right text-xs text-zinc-600 dark:text-zinc-300">weight {weight}</span>
            </div>
            {s.evidence && <p className="mt-0.5 text-xs text-zinc-600 dark:text-zinc-300">{s.category}: {s.evidence}</p>}
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
      <p className="text-xs text-zinc-600 dark:text-zinc-300">From: {sender}</p>
      <p className="mt-1 rounded bg-zinc-100 p-3 text-sm leading-relaxed dark:bg-zinc-900">{parts}</p>
      <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-300">Highlighted phrases are the wording that raised risk.</p>
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
              <span className={done[i] ? "text-zinc-600 dark:text-zinc-300 line-through" : ""}>{step}</span>
            </label>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-sm text-zinc-600 dark:text-zinc-300" aria-live="polite">
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
    <Card title="Reasoning model" aside={<span className="text-xs text-zinc-600 dark:text-zinc-300">read first · {r.model}{r.local ? " · on this computer" : ""}</span>}>
      <p className="text-sm leading-relaxed">{r.summary}</p>
      <dl className="mt-3 grid gap-x-4 gap-y-1 text-sm sm:grid-cols-2">
        {r.claimed_identity && (
          <div>
            <dt className="text-xs text-zinc-600 dark:text-zinc-300">Sender claims to be</dt>
            <dd>{r.claimed_identity}</dd>
          </div>
        )}
        {r.request_type && (
          <div>
            <dt className="text-xs text-zinc-600 dark:text-zinc-300">What is being asked</dt>
            <dd>{r.request_type.replace(/_/g, " ")}</dd>
          </div>
        )}
        {r.concern && (
          <div>
            <dt className="text-xs text-zinc-600 dark:text-zinc-300">Model&apos;s concern (advisory)</dt>
            <dd>{CONCERN[r.concern]}</dd>
          </div>
        )}
      </dl>
      {r.inconsistencies.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-semibold text-zinc-600 dark:text-zinc-300">Does not add up</p>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
            {r.inconsistencies.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        </div>
      )}
      {r.innocent_explanations.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-semibold text-zinc-600 dark:text-zinc-300">Genuine explanations to consider</p>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
            {r.innocent_explanations.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        </div>
      )}
      <p className="mt-3 text-xs text-zinc-600 dark:text-zinc-300">{r.note}</p>
    </Card>
  );
}

export function OfficialContactCard({ c }: { c: OfficialContact }) {
  return (
    <Card title={`On record for ${c.organisation}`}>
      <p className="text-sm">
        Official email domain{c.domains.length > 1 ? "s" : ""}: <strong>{c.domains.join(", ")}</strong>
      </p>
      <p className="mt-1 text-sm">
        Official site:{" "}
        <a href={c.site} target="_blank" rel="noopener noreferrer" className="underline">
          {c.site}
        </a>
      </p>
      <p className="mt-2 text-xs text-zinc-600 dark:text-zinc-300">
        Open the official site yourself and use the contact details there, never those in the message. This short list is
        curated by the team, not by the AI, and may be out of date.
      </p>
    </Card>
  );
}

export function FollowUpCard({ items, onSubmit, busy }: { items: FollowUp[]; onSubmit: (v: { email?: string; org?: string }) => void; busy: boolean }) {
  const [email, setEmail] = useState("");
  const [org, setOrg] = useState("");
  const wantsEmail = items.some((i) => i.id === "sender_email");
  const wantsOrg = items.some((i) => i.id === "organisation");
  const ready = (wantsEmail && email.trim()) || (wantsOrg && org.trim());
  return (
    <Card title="One more thing that would help">
      <ul className="space-y-1 text-sm">
        {items.map((i) => (
          <li key={i.id}>{i.question}</li>
        ))}
      </ul>
      <form
        className="mt-3 flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (ready) onSubmit({ email: email.trim() || undefined, org: org.trim() || undefined });
        }}
      >
        {wantsEmail && (
          <div>
            <label htmlFor="fu-email" className="block text-xs text-zinc-600 dark:text-zinc-300">Sender&apos;s email address</label>
            <input
              id="fu-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              maxLength={254}
              placeholder="name@gmail.com"
              className="mt-1 rounded-lg border border-zinc-300 bg-transparent p-2 text-sm dark:border-zinc-700"
            />
          </div>
        )}
        {wantsOrg && (
          <div>
            <label htmlFor="fu-org" className="block text-xs text-zinc-600 dark:text-zinc-300">Company they claim to be from</label>
            <input
              id="fu-org"
              type="text"
              value={org}
              onChange={(e) => setOrg(e.target.value)}
              maxLength={120}
              placeholder="e.g. Acme Corp"
              className="mt-1 rounded-lg border border-zinc-300 bg-transparent p-2 text-sm dark:border-zinc-700"
            />
          </div>
        )}
        <button
          type="submit"
          disabled={!ready || busy}
          className="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-40 dark:bg-zinc-100 dark:text-zinc-900"
        >
          {busy ? "Re-checking…" : "Re-check"}
        </button>
      </form>
      <p className="mt-2 text-xs text-zinc-600 dark:text-zinc-300">The message is not read again from scratch, so this is quick.</p>
    </Card>
  );
}

const AUTH_STYLE = (v: string | null) =>
  v === "pass" || v === "bestguesspass"
    ? "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/50 dark:text-emerald-100"
    : v === "fail" || v === "permerror" || v === "softfail"
      ? "bg-red-100 text-red-900 dark:bg-red-900/50 dark:text-red-100"
      : "bg-zinc-200 text-zinc-800 dark:bg-zinc-800 dark:text-zinc-200";

export function HeaderCard({ h, isolation }: { h: HeaderSummary; isolation?: string }) {
  return (
    <Card title="What the email headers say">
      <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-2">
        {(h.from_display || h.from_email) && (
          <div>
            <dt className="text-xs text-zinc-600 dark:text-zinc-300">Sent from</dt>
            <dd className="break-words">
              {h.from_display ? `${h.from_display} ` : ""}
              {h.from_email ? `<${h.from_email}>` : ""}
            </dd>
          </div>
        )}
        {h.reply_to && (
          <div>
            <dt className="text-xs text-zinc-600 dark:text-zinc-300">Replies go to</dt>
            <dd className="break-words">{h.reply_to}</dd>
          </div>
        )}
        {h.subject && (
          <div className="sm:col-span-2">
            <dt className="text-xs text-zinc-600 dark:text-zinc-300">Subject</dt>
            <dd className="break-words">{h.subject}</dd>
          </div>
        )}
        {h.sending_ip && (
          <div className="sm:col-span-2">
            <dt className="text-xs text-zinc-600 dark:text-zinc-300">Sending mail server</dt>
            <dd className="break-words">
              {h.sending_ip}
              {h.sending_host ? ` (${h.sending_host})` : ""}
            </dd>
          </div>
        )}
      </dl>
      <div className="mt-3 flex flex-wrap gap-2 text-xs" aria-label="Sender authentication results">
        {(["SPF", "DKIM", "DMARC"] as const).map((k) => {
          const v = h[k.toLowerCase() as "spf" | "dkim" | "dmarc"];
          return (
            <span key={k} className={`rounded px-2 py-0.5 font-medium ${AUTH_STYLE(v)}`}>
              {k}: {v ?? "not found"}
            </span>
          );
        })}
      </div>
      <p className="mt-3 text-xs text-zinc-600 dark:text-zinc-300">
        SPF, DKIM and DMARC are the receiving mail service&apos;s own check that the sender was allowed to send for that
        domain. Passing does not prove the content is honest, because a scammer&apos;s own domain passes too. Only these fields
        are shown; your own address and the rest of the headers are discarded.
      </p>
      <SandboxNote container={isolation === "container"} what="These headers were parsed" />
    </Card>
  );
}

/** Says plainly whether untrusted input was handled inside a private, throwaway container. */
export function SandboxNote({ container, what }: { container: boolean; what: string }) {
  return (
    <p className="mt-2 flex items-start gap-2 text-xs text-zinc-600 dark:text-zinc-300">
      <span
        className={`mt-0.5 inline-block size-2 shrink-0 rounded-full ${container ? "bg-emerald-500" : "bg-amber-500"}`}
        aria-hidden
      />
      <span>
        {container
          ? `${what} inside a private, throwaway container: no network, read-only, limited memory, and deleted afterwards.`
          : `${what} directly by the server, because no sandbox container is available. Start Docker Desktop and build the sandbox image to isolate it.`}
      </span>
    </p>
  );
}

const CONCERN_LABEL: Record<string, string> = { low: "Low", medium: "Medium", high: "High" };

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value) return null;
  return (
    <div>
      <dt className="text-xs text-zinc-600 dark:text-zinc-300">{label}</dt>
      <dd className="break-words text-sm">{value}</dd>
    </div>
  );
}

/** What the reading model found in the document. Every value shown was found verbatim in the document. */
export function DocumentReadingCard({ content }: { content: ContentReport }) {
  const r = content.reading;
  const f = content.facts;
  if (!r || r.status !== "used" || !f) {
    return (
      <Card title="What the document says">
        <p className="text-sm" role="status">
          <strong>{r?.status === "failed" ? "The reading model could not be used." : "No reading model ran."}</strong>{" "}
          {r?.note} Only the fixed checks below were applied to the contents.
        </p>
      </Card>
    );
  }
  return (
    <Card title="What the document says" aside={<span className="text-xs text-zinc-600 dark:text-zinc-300">read first · {r.model}{r.local ? " · on this computer" : ""}</span>}>
      <p className="text-sm leading-relaxed">{r.summary}</p>
      <dl className="mt-3 grid gap-x-4 gap-y-2 sm:grid-cols-2">
        <Field label="Looks like" value={f.document_type.replace(/_/g, " ")} />
        <Field label="Issued by" value={f.issuer} />
        <Field label="Addressed to" value={f.recipient} />
        <Field label="Total" value={f.total_amount} />
        <Field label="Pay to (account name)" value={f.account_holder} />
        <Field label="Dates" value={f.dates.join(", ")} />
        <Field label="Model's concern (advisory)" value={r.concern ? CONCERN_LABEL[r.concern] : null} />
      </dl>
      {f.payment_details.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-semibold text-zinc-600 dark:text-zinc-300">Payment details as written</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm">
            {f.payment_details.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        </div>
      )}
      {r.inconsistencies.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-semibold text-zinc-600 dark:text-zinc-300">Does not add up (the model&apos;s view, for information only)</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm">
            {r.inconsistencies.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        </div>
      )}
      <p className="mt-3 text-xs text-zinc-600 dark:text-zinc-300">{r.note}</p>
    </Card>
  );
}

function idStatus(i: Identifier): { text: string; cls: string } {
  if (i.valid === false) return { text: "Impossible", cls: "bg-red-100 text-red-900 dark:bg-red-900/50 dark:text-red-100" };
  if (i.valid === true) return { text: "Passes its check", cls: "bg-zinc-200 text-zinc-800 dark:bg-zinc-800 dark:text-zinc-200" };
  return { text: "Not checkable", cls: "bg-zinc-200 text-zinc-800 dark:bg-zinc-800 dark:text-zinc-200" };
}

/** Tax, bank and payment identifiers found in the document, with the result of their own check digits. */
export function IdentifiersCard({ items }: { items: Identifier[] }) {
  return (
    <Card title="Identifiers in the document">
      <ul className="divide-y divide-zinc-200 dark:divide-zinc-800">
        {items.map((i) => {
          const st = idStatus(i);
          return (
            <li key={`${i.kind}-${i.value}`} className="flex items-start justify-between gap-3 py-2 text-sm">
              <div className="min-w-0">
                <p>
                  <span className="font-medium">{i.kind}</span> <span className="break-all font-mono text-xs">{i.value}</span>
                </p>
                {i.note && <p className="text-xs text-zinc-600 dark:text-zinc-300">{i.note}</p>}
              </div>
              <span className={`shrink-0 rounded px-2 py-0.5 text-xs font-medium ${st.cls}`}>{st.text}</span>
            </li>
          );
        })}
      </ul>
      <p className="mt-2 text-xs text-zinc-600 dark:text-zinc-300">
        A check digit can prove a number is impossible, but not that it belongs to this vendor: anyone can compute a valid one.
        Confirm ownership with the official registry or the vendor.
      </p>
    </Card>
  );
}
