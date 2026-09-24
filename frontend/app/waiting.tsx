"use client";

import { useEffect, useState } from "react";

import OnboardCard from "@/components/ui/onboard-card";

/**
 * Shown while a check is running. The three steps are honest about what is happening:
 * the request has been received, the reading is in progress (this is the long part, especially with
 * a model running on this computer), and the checks on the evidence come after. The bar is an activity
 * indicator, not a percentage: the real time is not known in advance.
 *
 * It appears only after a short delay so quick checks do not flash it.
 */
export function Waiting({ label, note, delay = 600 }: { label: string; note?: string; delay?: number }) {
  const [show, setShow] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setShow(true), delay);
    return () => clearTimeout(t);
  }, [delay]);

  return (
    <div role="status" aria-live="polite" className="mt-4">
      <span className="sr-only">
        {label} {note}
      </span>
      {show && (
        <div aria-hidden="true" className="flex flex-col items-center">
          <OnboardCard step1="Request received" step2={label} step3="Verifying the evidence" />
          {note && <p className="mt-1 text-center text-sm text-zinc-500">{note}</p>}
        </div>
      )}
    </div>
  );
}
