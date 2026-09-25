"use client";

import { useEffect, useState } from "react";

import Loader from "@/components/ui/loader-4";

/**
 * A small inline loader for short waits (reading a file). It appears only after a short delay so quick
 * checks do not flash it. The message check uses the full-window AnalysisOverlay instead.
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
        <div aria-hidden="true" className="flex flex-col items-center gap-2 py-2">
          <Loader cellSize={16} />
          <p className="text-sm text-zinc-600 dark:text-zinc-300">{label}</p>
          {note && <p className="text-xs text-zinc-600 dark:text-zinc-300">{note}</p>}
        </div>
      )}
    </div>
  );
}
