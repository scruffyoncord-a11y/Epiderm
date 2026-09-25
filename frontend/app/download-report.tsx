"use client";

import { Download } from "lucide-react";

/** The last thing on the page. Prints the result exactly as shown (the print styles hide the buttons and badge): choose "Save as PDF". */
export function DownloadReport() {
  function save() {
    const previous = document.title;
    document.title = `Epiderm report ${new Date().toISOString().slice(0, 10)}`; // becomes the suggested file name
    window.print();
    document.title = previous;
  }

  return (
    <section className="no-print tg-card flex flex-wrap items-center justify-between gap-4 p-5" aria-label="Download report">
      <div>
        <p className="text-base font-semibold">Keep a record</p>
        <p className="mt-0.5 text-sm text-zinc-600 dark:text-zinc-300">
          Saves this result as a PDF, just as you see it. In the window that opens, choose <strong>Save as PDF</strong>.
        </p>
      </div>
      <button
        type="button"
        onClick={save}
        className="inline-flex items-center gap-2 rounded-lg bg-zinc-900 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-white"
      >
        <Download className="size-4" aria-hidden />
        Download report
      </button>
    </section>
  );
}
