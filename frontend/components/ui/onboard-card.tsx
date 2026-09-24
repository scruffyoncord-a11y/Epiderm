"use client";

import { Check, Circle, Loader } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";

import { cn } from "@/lib/utils";

export type Step = { label: string; detail?: string };

interface OnboardCardProps {
  steps: Step[];
  /** The step in progress (0-based). Earlier steps show as done, later ones as upcoming. */
  active: number;
  /** Every step is finished. */
  complete?: boolean;
}

/*
 * Adapted from the 21st.dev "onboard-card". Instead of three static stacked cards, the steps are slides in a
 * carousel: as work moves on, the row swipes so the current step sits in the middle, the finished one slips
 * to the left with a tick, and the next one slides in from the right.
 * - Tailwind v4 (`bg-linear-to-br`, CSS variables), lucide-react icons.
 * - Honours "reduce motion": no swipe or spinning, the state changes instantly.
 * - State is also exposed as data attributes / aria-current so it can be read without watching the animation.
 */
const VIEW = 340; // px, width of the window
const SLIDE = 220; // px, width of one slide
const GAP = 12; // px between slides

export default function OnboardCard({ steps, active, complete = false }: OnboardCardProps) {
  const reduceMotion = useReducedMotion();
  const current = Math.min(Math.max(active, 0), steps.length - 1);
  const x = (VIEW - SLIDE) / 2 - current * (SLIDE + GAP);
  const spring = reduceMotion ? { duration: 0 } : ({ type: "spring", stiffness: 210, damping: 27 } as const);

  return (
    <div className="flex flex-col items-center gap-3" data-complete={complete}>
      <div className="relative overflow-hidden py-1" style={{ width: VIEW }}>
        <motion.ol
          className="flex list-none p-0"
          style={{ gap: GAP, width: "max-content" }}
          initial={false}
          animate={{ x }}
          transition={spring}
        >
          {steps.map((step, i) => {
            const state = complete || i < current ? "done" : i === current ? "active" : "upcoming";
            return (
              <motion.li
                key={step.label}
                data-state={state}
                aria-current={state === "active" ? "step" : undefined}
                className="flex flex-col justify-center gap-2 rounded-md border bg-linear-to-br from-neutral-100 to-neutral-50 px-3 py-3 dark:from-neutral-800 dark:to-neutral-950"
                style={{ width: SLIDE }}
                initial={false}
                animate={{ scale: state === "active" ? 1 : 0.88, opacity: state === "active" ? 1 : state === "done" ? 0.6 : 0.45 }}
                transition={spring}
              >
                <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                  <StepIcon state={state} reduceMotion={!!reduceMotion} />
                  <span>{step.label}</span>
                </div>
                {step.detail && <p className="pl-7 text-xs text-neutral-500 dark:text-neutral-400">{step.detail}</p>}
                <div className="ml-7 h-1.5 overflow-hidden rounded-full bg-neutral-200 dark:bg-neutral-700">
                  {state === "done" && <div className="h-full w-full bg-green-500" />}
                  {state === "active" && <ActivityBar reduceMotion={!!reduceMotion} />}
                </div>
              </motion.li>
            );
          })}
        </motion.ol>

        {/* soft edges so neighbouring slides fade into the page */}
        <div className="pointer-events-none absolute inset-y-0 left-0 w-10 [background-image:linear-gradient(to_right,var(--background)_10%,transparent_100%)]" />
        <div className="pointer-events-none absolute inset-y-0 right-0 w-10 [background-image:linear-gradient(to_left,var(--background)_10%,transparent_100%)]" />
      </div>

      <div className="flex items-center gap-1.5" aria-hidden="true">
        {steps.map((step, i) => (
          <span
            key={step.label}
            className={cn(
              "h-1.5 rounded-full transition-all",
              complete || i < current ? "w-1.5 bg-green-500" : i === current ? "w-4 bg-green-500" : "w-1.5 bg-neutral-300 dark:bg-neutral-600",
            )}
          />
        ))}
      </div>
      <p className="text-xs text-neutral-500 dark:text-neutral-400">
        {complete ? "All checks complete" : `Step ${current + 1} of ${steps.length}`}
      </p>
    </div>
  );
}

function StepIcon({ state, reduceMotion }: { state: "done" | "active" | "upcoming"; reduceMotion: boolean }) {
  if (state === "done") {
    return (
      <span className="relative inline-flex size-5 items-center justify-center rounded-full bg-green-500 text-background">
        <Check className="size-3" strokeWidth={4} aria-hidden />
      </span>
    );
  }
  if (state === "active") return <Loader className={cn("size-5", !reduceMotion && "animate-spin")} aria-hidden />;
  return <Circle className="size-5 text-neutral-400 dark:text-neutral-500" aria-hidden />;
}

function ActivityBar({ reduceMotion }: { reduceMotion: boolean }) {
  if (reduceMotion) return <div className="h-full w-1/2 bg-green-500" />;
  return (
    <motion.div
      className="h-full w-2/5 rounded-full bg-green-500"
      initial={{ x: "-100%" }}
      animate={{ x: "260%" }}
      transition={{ duration: 1.3, ease: "easeInOut", repeat: Infinity }}
    />
  );
}
