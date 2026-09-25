"use client";

import { ShieldAlert, ShieldCheck, ShieldX } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import type { RiskFactor, RiskSummary } from "./types";

type Tone = { text: string; stroke: string; fill: string; soft: string; ring: string };

const TONE: Record<RiskSummary["verdict"], Tone> = {
  legit: { text: "text-emerald-500", stroke: "#10b981", fill: "bg-emerald-500", soft: "bg-emerald-500/10", ring: "border-emerald-500/40" },
  suspicious: { text: "text-amber-500", stroke: "#f59e0b", fill: "bg-amber-500", soft: "bg-amber-500/10", ring: "border-amber-500/40" },
  not_legit: { text: "text-red-500", stroke: "#ef4444", fill: "bg-red-500", soft: "bg-red-500/10", ring: "border-red-500/40" },
};

const VERDICT_ICON = { legit: ShieldCheck, suspicious: ShieldAlert, not_legit: ShieldX };
const VERDICT_LINE: Record<RiskSummary["verdict"], string> = {
  legit: "No warning signs found in what we could check.",
  suspicious: "Some warning signs. Check with the sender through a contact you already trust before acting.",
  not_legit: "Strong warning signs. Do not pay, reply, or open links until you have verified it independently.",
};

function riskColor(value: number): string {
  return value >= 70 ? "bg-red-500" : value >= 40 ? "bg-amber-500" : value > 0 ? "bg-yellow-400" : "bg-zinc-600";
}

/** Counts from 0 up to the target once, so the score "lands" when the result appears. */
function useCountUp(target: number, instant: boolean): number {
  const [value, setValue] = useState(0);
  useEffect(() => {
    const duration = instant ? 0 : 1100;
    const start = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const t = duration === 0 ? 1 : Math.min(1, (now - start) / duration);
      setValue(Math.round(target * (1 - Math.pow(1 - t, 3))));
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target, instant]);
  return value;
}

function ScoreGauge({ risk, reduce }: { risk: RiskSummary; reduce: boolean }) {
  const tone = TONE[risk.verdict];
  const shown = useCountUp(risk.security_score, reduce);
  const r = 84;
  const c = 2 * Math.PI * r;
  return (
    <div className="relative mx-auto size-52 shrink-0" role="img" aria-label={`Security score ${risk.security_score} out of 100`}>
      <svg viewBox="0 0 200 200" className="size-full -rotate-90">
        <circle cx="100" cy="100" r={r} fill="none" strokeWidth="14" className="stroke-zinc-200 dark:stroke-zinc-800" />
        {[25, 50, 75].map((p) => (
          <line key={p} x1="100" y1="8" x2="100" y2="20" transform={`rotate(${p * 3.6} 100 100)`} className="stroke-zinc-400/50" strokeWidth="2" />
        ))}
        <motion.circle
          cx="100" cy="100" r={r} fill="none" strokeWidth="14" strokeLinecap="round" stroke={tone.stroke}
          strokeDasharray={c}
          initial={{ strokeDashoffset: c }}
          animate={{ strokeDashoffset: c * (1 - risk.security_score / 100) }}
          transition={{ duration: reduce ? 0 : 1.1, ease: [0.22, 1, 0.36, 1] }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={`font-serif text-6xl font-bold tabular-nums ${tone.text}`}>{shown}</span>
        <span className="mt-1 text-[11px] font-medium uppercase tracking-[0.2em] text-zinc-600 dark:text-zinc-300">Security score</span>
        <span className="text-[11px] text-zinc-600 dark:text-zinc-300">risk {risk.risk_score}/100</span>
      </div>
    </div>
  );
}

function EvidenceDonut({ risk }: { risk: RiskSummary }) {
  const parts = [
    { label: "Warning signs", n: risk.suspicious, color: "#ef4444" },
    { label: "Reassuring", n: risk.reassuring, color: "#10b981" },
    { label: "Could not verify", n: risk.unknown, color: "#71717a" },
  ];
  const total = parts.reduce((a, p) => a + p.n, 0);
  const r = 34;
  const c = 2 * Math.PI * r;
  let offset = 0;
  return (
    <div className="flex items-center gap-4">
      <svg viewBox="0 0 90 90" className="size-24 -rotate-90" role="img" aria-label={parts.map((p) => `${p.label} ${p.n}`).join(", ")}>
        <circle cx="45" cy="45" r={r} fill="none" strokeWidth="12" className="stroke-zinc-200 dark:stroke-zinc-800" />
        {total > 0 &&
          parts.map((p) => {
            const len = (p.n / total) * c;
            const el = p.n > 0 && (
              <circle key={p.label} cx="45" cy="45" r={r} fill="none" strokeWidth="12" stroke={p.color}
                strokeDasharray={`${len} ${c - len}`} strokeDashoffset={-offset} />
            );
            offset += len;
            return el;
          })}
      </svg>
      <ul className="space-y-1 text-sm">
        {parts.map((p) => (
          <li key={p.label} className="flex items-center gap-2">
            <span className="size-2.5 rounded-full" style={{ background: p.color }} aria-hidden />
            <span className="w-8 font-semibold tabular-nums">{p.n}</span>
            <span className="text-zinc-600 dark:text-zinc-300">{p.label}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function AreaBars({ risk, reduce }: { risk: RiskSummary; reduce: boolean }) {
  if (risk.areas.length === 0) return <p className="text-sm text-zinc-600 dark:text-zinc-300">No areas produced any findings.</p>;
  return (
    <ul className="space-y-3">
      {risk.areas.map((a, i) => (
        <li key={a.name}>
          <div className="flex items-baseline justify-between text-sm">
            <span>{a.name}</span>
            <span className="tabular-nums text-zinc-600 dark:text-zinc-300">
              <strong className="text-inherit">{a.risk}</strong>/100
            </span>
          </div>
          <div className="mt-1 h-2.5 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
            <motion.div
              className={`h-full rounded-full ${riskColor(a.risk)}`}
              initial={{ width: 0 }}
              animate={{ width: `${Math.max(a.risk, a.risk > 0 ? 3 : 0)}%` }}
              transition={{ duration: reduce ? 0 : 0.8, delay: reduce ? 0 : 0.15 + i * 0.08 }}
            />
          </div>
          <p className="mt-0.5 text-xs text-zinc-600 dark:text-zinc-300">
            {a.suspicious} warning{a.suspicious === 1 ? "" : "s"} · {a.reassuring} reassuring · {a.unknown} unverified
          </p>
        </li>
      ))}
    </ul>
  );
}

function cellColor(l: number, i: number): string {
  const v = l * i;
  if (v >= 16) return "bg-red-500/70";
  if (v >= 10) return "bg-orange-500/60";
  if (v >= 5) return "bg-amber-400/50";
  return "bg-emerald-500/35";
}

function RiskMatrix({ factors }: { factors: RiskFactor[] }) {
  const [picked, setPicked] = useState<string | null>(null);
  const cells = useMemo(() => {
    const m = new Map<string, RiskFactor[]>();
    for (const f of factors) {
      const k = `${f.likelihood}-${f.impact}`;
      m.set(k, [...(m.get(k) ?? []), f]);
    }
    return m;
  }, [factors]);
  const chosen = picked ? cells.get(picked) ?? [] : [];
  return (
    <div>
      <div className="flex gap-2">
        <div className="flex w-4 items-center justify-center">
          <span className="-rotate-90 whitespace-nowrap text-[11px] uppercase tracking-wider text-zinc-600 dark:text-zinc-300">Likelihood</span>
        </div>
        <div className="flex-1">
          <div className="grid grid-cols-5 gap-1" role="grid" aria-label="Risk matrix: likelihood by impact">
            {[5, 4, 3, 2, 1].map((l) =>
              [1, 2, 3, 4, 5].map((i) => {
                const k = `${l}-${i}`;
                const here = cells.get(k) ?? [];
                return (
                  <button
                    key={k}
                    type="button"
                    role="gridcell"
                    disabled={here.length === 0}
                    onClick={() => setPicked(picked === k ? null : k)}
                    title={here.map((f) => f.label).join("\n") || `Likelihood ${l}, impact ${i}`}
                    aria-label={`Likelihood ${l}, impact ${i}: ${here.length} finding(s)`}
                    className={`flex aspect-[4/3] items-center justify-center rounded text-sm font-bold text-white transition ${cellColor(l, i)} ${
                      here.length ? "cursor-pointer ring-white/70 hover:ring-2" : "opacity-60"
                    } ${picked === k ? "ring-2" : ""}`}
                  >
                    {here.length > 0 && <span className="grid size-7 place-items-center rounded-full bg-black/45">{here.length}</span>}
                  </button>
                );
              }),
            )}
          </div>
          <p className="mt-1 text-center text-[11px] uppercase tracking-wider text-zinc-600 dark:text-zinc-300">Impact →</p>
        </div>
      </div>
      <div className="mt-2 min-h-5 text-xs text-zinc-600 dark:text-zinc-300" aria-live="polite">
        {chosen.length > 0 ? (
          <ul className="list-disc space-y-0.5 pl-5">
            {chosen.map((f) => (
              <li key={`${f.source}-${f.id}`}>
                <span className="text-inherit">{f.label}</span> ({f.area}
                {f.source ? `, ${f.source}` : ""})
              </li>
            ))}
          </ul>
        ) : factors.length > 0 ? (
          "Select a numbered square to see its findings."
        ) : (
          "No warning signs to place on the matrix."
        )}
      </div>
    </div>
  );
}

function TopFactors({ factors, reduce }: { factors: RiskFactor[]; reduce: boolean }) {
  const top = factors.slice(0, 6);
  if (top.length === 0) return null;
  return (
    <ol className="space-y-2">
      {top.map((f, i) => (
        <li key={`${f.source}-${f.id}`} className="grid grid-cols-[1fr_auto] items-center gap-x-3 text-sm">
          <span className="truncate" title={f.label}>
            {f.label}
            <span className="ml-1 text-xs text-zinc-600 dark:text-zinc-300">· {f.area}{f.source ? ` · ${f.source}` : ""}</span>
          </span>
          <span className="tabular-nums text-xs text-zinc-600 dark:text-zinc-300">{f.weight}</span>
          <div className="col-span-2 h-1.5 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
            <motion.div
              className={`h-full rounded-full ${riskColor(f.weight)}`}
              initial={{ width: 0 }}
              animate={{ width: `${f.weight}%` }}
              transition={{ duration: reduce ? 0 : 0.7, delay: reduce ? 0 : 0.3 + i * 0.06 }}
            />
          </div>
        </li>
      ))}
    </ol>
  );
}

function Panel({ title, children, className = "" }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={`tg-card p-5 ${className}`}>
      <h3 className="mb-4 text-xs font-semibold uppercase tracking-[0.15em] text-zinc-700 dark:text-zinc-200">{title}</h3>
      {children}
    </section>
  );
}

/** The headline of every check: a bold verdict, the security score, and charts built from the same signals. */
export function RiskDashboard({ risk }: { risk: RiskSummary }) {
  const reduce = !!useReducedMotion();
  const tone = TONE[risk.verdict];
  const Icon = VERDICT_ICON[risk.verdict];
  return (
    <div className="space-y-4">
      <motion.section
        initial={reduce ? false : { opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className={`tg-card p-6 ${tone.ring} ${tone.soft}`}
        role="status"
        aria-label={`Verdict: ${risk.verdict_label}. Security score ${risk.security_score} out of 100.`}
      >
        <div className="flex flex-col items-center gap-6 sm:flex-row">
          <ScoreGauge risk={risk} reduce={reduce} />
          <div className="min-w-0 flex-1 text-center sm:text-left">
            <div className={`flex items-center justify-center gap-3 sm:justify-start ${tone.text}`}>
              <Icon className="size-7 shrink-0" aria-hidden />
              <p className="font-serif text-3xl font-bold uppercase tracking-[0.12em]">{risk.verdict_label}</p>
            </div>
            <p className="mt-2 text-base font-medium text-zinc-800 dark:text-zinc-100">{VERDICT_LINE[risk.verdict]}</p>
            <div className="mt-3 flex flex-wrap justify-center gap-2 text-xs sm:justify-start">
              <span className={`rounded-full px-2.5 py-1 font-semibold uppercase text-white ${tone.fill}`}>{risk.level} risk</span>
              <span className="rounded-full bg-zinc-200 px-2.5 py-1 dark:bg-zinc-800">{risk.suspicious} warning sign{risk.suspicious === 1 ? "" : "s"}</span>
              <span className="rounded-full bg-zinc-200 px-2.5 py-1 dark:bg-zinc-800">{risk.areas.length} area{risk.areas.length === 1 ? "" : "s"} checked</span>
            </div>
            {risk.parts.length > 0 && (
              <ul className="mt-4 space-y-1.5">
                {risk.parts.map((p) => {
                  const t = TONE[p.verdict as RiskSummary["verdict"]] ?? TONE.suspicious;
                  return (
                    <li key={p.name} className="grid grid-cols-[minmax(0,10rem)_1fr_auto] items-center gap-2 text-sm">
                      <span className="truncate" title={p.name}>{p.name}</span>
                      <div className="h-2 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
                        <div className={`h-full rounded-full ${t.fill}`} style={{ width: `${p.risk_score}%` }} />
                      </div>
                      <span className={`text-xs font-semibold tabular-nums ${t.text}`}>risk {p.risk_score}</span>
                    </li>
                  );
                })}
              </ul>
            )}
            <p className="mt-3 text-xs text-zinc-600 dark:text-zinc-300">A risk assessment, not proof. A person makes the final decision.</p>
          </div>
        </div>
      </motion.section>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Panel title="Risk by area">
          <AreaBars risk={risk} reduce={reduce} />
        </Panel>
        <Panel title="Risk matrix">
          <RiskMatrix factors={risk.matrix} />
        </Panel>
        <Panel title="Evidence mix">
          <EvidenceDonut risk={risk} />
        </Panel>
        <Panel title="Biggest warning signs">
          {risk.matrix.length > 0 ? <TopFactors factors={risk.matrix} reduce={reduce} /> : <p className="text-sm text-zinc-600 dark:text-zinc-300">None.</p>}
        </Panel>
      </div>
      <p className="text-xs text-zinc-600 dark:text-zinc-300">How the score works: {risk.basis}</p>
    </div>
  );
}
