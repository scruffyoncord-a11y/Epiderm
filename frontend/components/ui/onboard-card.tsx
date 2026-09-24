"use client";

import { Check, Loader } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

interface OnboardCardProps {
  /** How long the middle bar takes to fill, in ms. It then restarts, so it works for waits of any length. */
  duration?: number;
  step1?: string;
  step2?: string;
  step3?: string;
}

/*
 * Adapted from the 21st.dev "onboard-card" for this project:
 * - Tailwind v4: `bg-linear-to-br` and CSS variables (`var(--background)`) instead of v3's `bg-gradient-to-br` and `theme()`.
 * - `text-foreground` (defined in globals.css) instead of shadcn's `text-primary`.
 * - lucide-react icons instead of react-icons.
 * - Honours "reduce motion": no spinning or looping when the user asks their system for less animation.
 */
const OnboardCard = ({
  duration = 3000,
  step1 = "Welcome Aboard",
  step2 = "Verifying Details",
  step3 = "Account Created",
}: OnboardCardProps) => {
  const reduceMotion = useReducedMotion();
  const [progress, setProgress] = useState(0);
  const [animateKey, setAnimateKey] = useState(0);

  useEffect(() => {
    if (reduceMotion) return;
    const forward = setTimeout(() => setProgress(100), 100);
    const reset = setTimeout(() => setAnimateKey((k) => k + 1), duration + 2000);
    return () => {
      clearTimeout(forward);
      clearTimeout(reset);
    };
  }, [animateKey, duration, reduceMotion]);

  const card =
    "flex min-w-[250px] flex-col justify-center gap-2 rounded-md border bg-linear-to-br from-neutral-100 to-neutral-50 py-2 pl-3 pr-16 dark:from-neutral-800 dark:to-neutral-950";

  return (
    <div className={cn("relative", "flex flex-col items-center justify-center gap-1 p-1")}>
      <div className={cn(card, "scale-[0.9] opacity-80")}>
        <div className="flex items-center justify-start gap-2 text-xs text-foreground">
          <Loader className="size-4" aria-hidden />
          <div>{step3}</div>
        </div>
        <div className="ml-5 h-1.5 w-full overflow-hidden rounded-full bg-neutral-200 dark:bg-neutral-700" />
      </div>

      <div className={card}>
        <div className="flex items-center justify-start gap-1.5 text-xs text-foreground">
          <Loader className={cn("size-4", !reduceMotion && "animate-spin")} aria-hidden />
          <div>{step2}</div>
        </div>
        <div className="ml-5 h-1.5 w-full overflow-hidden rounded-full bg-neutral-200 dark:bg-neutral-700">
          <motion.div
            key={animateKey}
            className="h-full bg-green-500"
            initial={{ width: reduceMotion ? "50%" : 0 }}
            animate={{ width: reduceMotion ? "50%" : `${progress}%` }}
            transition={{ duration: reduceMotion ? 0 : duration / 1000, ease: "easeInOut" }}
          />
        </div>
      </div>

      <div className={cn(card, "scale-[0.9] opacity-80")}>
        <div className="flex items-center justify-start text-xs text-foreground">
          <div className="relative">
            <svg width="20" height="20" aria-hidden>
              <circle cx="10" cy="10" r="5" fill="#22c55e" />
            </svg>
            <div className="absolute inset-0 flex items-center justify-center text-background">
              <Check className="size-2" strokeWidth={4} aria-hidden />
            </div>
          </div>
          <div>{step1}</div>
        </div>
        <div className="ml-5 h-1.5 w-full overflow-hidden rounded-full bg-green-500" />
      </div>

      <div className="pointer-events-none absolute top-0 h-[40%] w-full [background-image:linear-gradient(to_bottom,var(--background)_20%,transparent_100%)]" />
      <div className="pointer-events-none absolute bottom-0 h-[40%] w-full [background-image:linear-gradient(to_top,var(--background)_20%,transparent_100%)]" />
    </div>
  );
};

export default OnboardCard;
