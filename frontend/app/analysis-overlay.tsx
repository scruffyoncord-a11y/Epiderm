"use client";

import { motion, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import OnboardCard, { type Step } from "@/components/ui/onboard-card";

const DWELL_MS = 650; // each slide stays long enough to be read, even when the real work is instant
const DWELL_REDUCED_MS = 250;
const HOLD_DONE_MS = 700; // the finished state is shown briefly before the overlay leaves
const EXIT_MS = 280;

/**
 * A full-window overlay, centred over a blurred page, that swipes through the steps of a running check.
 *
 * `stage` is the step the server has REALLY reached; the slides follow it, at most one per DWELL so a fast
 * check does not flash past. When `finished` is set the remaining slides play out, the "all done" state
 * is held for a moment, the overlay fades away and `onClosed` is called: only then does the caller show
 * the result.
 */
export function AnalysisOverlay({
  steps,
  stage,
  finished,
  onClosed,
}: {
  steps: Step[];
  stage: number;
  finished: boolean;
  onClosed: () => void;
}) {
  const reduceMotion = useReducedMotion();
  const total = steps.length;
  const [shown, setShown] = useState(0);
  const [leaving, setLeaving] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const closedRef = useRef(onClosed);

  useEffect(() => {
    closedRef.current = onClosed;
  }, [onClosed]);

  const target = finished ? total : Math.min(stage, total - 1);
  const dwell = reduceMotion ? DWELL_REDUCED_MS : DWELL_MS;

  // Follow the real progress one slide at a time.
  useEffect(() => {
    if (shown < target) {
      const t = setTimeout(() => setShown((s) => s + 1), dwell);
      return () => clearTimeout(t);
    }
    if (shown >= total) {
      const t = setTimeout(() => setLeaving(true), HOLD_DONE_MS);
      return () => clearTimeout(t);
    }
  }, [shown, target, total, dwell]);

  useEffect(() => {
    if (!leaving) return;
    const t = setTimeout(() => closedRef.current(), reduceMotion ? 0 : EXIT_MS);
    return () => clearTimeout(t);
  }, [leaving, reduceMotion]);

  // While it is open: the page behind cannot be scrolled or focused, and focus moves into the dialog.
  useEffect(() => {
    const main = document.querySelector("main");
    main?.setAttribute("inert", "");
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialogRef.current?.focus();
    return () => {
      main?.removeAttribute("inert");
      document.body.style.overflow = previousOverflow;
    };
  }, []);

  const active = Math.min(shown, total - 1);
  const complete = shown >= total;
  const spoken = complete ? "All checks complete" : `Step ${active + 1} of ${total}: ${steps[active].label}`;

  return createPortal(
    <motion.div
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/55 px-4 backdrop-blur-md"
      initial={{ opacity: reduceMotion ? 1 : 0 }}
      animate={{ opacity: leaving ? 0 : 1 }}
      transition={{ duration: reduceMotion ? 0 : 0.25 }}
      data-testid="analysis-overlay"
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="analysis-title"
        tabIndex={-1}
        className="flex max-w-full flex-col items-center gap-4 rounded-xl border border-neutral-200 bg-background/90 px-6 py-6 shadow-xl outline-none dark:border-neutral-800"
      >
        <h2 id="analysis-title" className="text-base font-semibold">
          Checking your evidence
        </h2>
        <OnboardCard steps={steps} active={active} complete={complete} />
        <p className="sr-only" role="status" aria-live="polite">
          {spoken}
        </p>
      </div>
    </motion.div>,
    document.body,
  );
}
