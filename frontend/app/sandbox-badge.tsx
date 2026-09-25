"use client";

import { LockKeyhole, ShieldAlert, ShieldCheck } from "lucide-react";
import { useState } from "react";

export type SandboxState = "standby" | "opening" | "active" | "off";

const LOOK: Record<SandboxState, { label: string; dot: string; text: string }> = {
  standby: { label: "Sandbox on standby", dot: "bg-zinc-400", text: "text-zinc-700 dark:text-zinc-200" },
  opening: { label: "Opening sandbox…", dot: "bg-amber-400 animate-pulse", text: "text-amber-700 dark:text-amber-300" },
  active: { label: "Sandbox active", dot: "bg-emerald-500", text: "text-emerald-700 dark:text-emerald-300" },
  off: { label: "Sandbox not running", dot: "bg-amber-500", text: "text-amber-700 dark:text-amber-300" },
};

const POINTS: Record<SandboxState, { title: string; items: string[] }> = {
  standby: {
    title: "Your private sandbox opens when you pick a check",
    items: [
      "Each check gets its own throwaway container.",
      "Nothing you enter or upload is stored.",
    ],
  },
  opening: {
    title: "Setting up your private container",
    items: ["This takes a moment. Nothing has been read yet."],
  },
  active: {
    title: "Your files are being handled in an isolated container",
    items: [
      "No network: the container cannot send anything out.",
      "Read-only disk, no admin rights, and strict memory and CPU limits.",
      "Your file is held in memory only. Nothing is written to disk or saved.",
      "The container is deleted when you leave, close the tab, or after 10 idle minutes.",
      "The AI model runs outside it. With a local model, your text stays on this computer.",
    ],
  },
  off: {
    title: "No sandbox is available right now",
    items: [
      "Docker is not running or the sandbox image is missing.",
      "Files and email headers are read directly by this app's server instead.",
      "Nothing is stored, but they are not isolated. Start Docker and reload to turn the sandbox on.",
    ],
  },
};

/** A corner badge that says, honestly, whether the sandbox is protecting the current check. */
export function SandboxBadge({ state }: { state: SandboxState }) {
  const [open, setOpen] = useState(false);
  const look = LOOK[state];
  const info = POINTS[state];
  const Icon = state === "active" ? ShieldCheck : state === "off" ? ShieldAlert : LockKeyhole;
  return (
    <div className="no-print fixed right-4 top-4 z-40 flex flex-col items-end gap-2 sm:right-8" onMouseLeave={() => setOpen(false)}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        onMouseEnter={() => setOpen(true)}
        aria-expanded={open}
        aria-controls="sandbox-info"
        className={`tg-card flex items-center gap-2 !rounded-full px-4 py-2 text-sm font-semibold ${look.text} focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2`}
      >
        <span className={`size-2.5 rounded-full ${look.dot}`} aria-hidden />
        <Icon className="size-4" aria-hidden />
        {look.label}
        {state === "active" && <span className="hidden font-normal text-zinc-700 dark:text-zinc-300 sm:inline">· your data is safe</span>}
      </button>
      {open && (
        <div id="sandbox-info" role="status" className="tg-card w-80 p-4 text-sm">
          <p className="font-semibold">{info.title}</p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-zinc-700 dark:text-zinc-300">
            {info.items.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
