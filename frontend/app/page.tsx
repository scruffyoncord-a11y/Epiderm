"use client";

import { useEffect, useRef, useState } from "react";

import Loader from "@/components/ui/loader-4";

import { Card } from "./components";
import { DocumentCheck } from "./document-check";
import { API, closeSession, openSession } from "./lib";
import { PhishingCheck } from "./phishing-check";

type Category = "phishing" | "document" | "persona";
type Session = { status: "idle" | "opening" | "ready" | "none"; id: string | null };

const CATEGORIES: { id: Category; title: string; blurb: string; status: string; ready: boolean }[] = [
  {
    id: "phishing",
    title: "Phishing & email verification",
    blurb: "A message or email you received. Is it trying to trick you, and is the sender who they claim to be? You can paste the email headers for a stronger check.",
    status: "Available",
    ready: true,
  },
  {
    id: "document",
    title: "Document verification",
    blurb: "An invoice, letter or scan. How was the file made, and was it changed afterwards? Reads PDFs, Word, Excel, PowerPoint and images.",
    status: "Available",
    ready: true,
  },
  {
    id: "persona",
    title: "Deepfake, persona & voice verification",
    blurb: "A photo, a profile or a voice. Image checks work now. Voice and video checks are not built yet.",
    status: "Partly available",
    ready: false,
  },
];

const MIN_OPENING_MS = 900; // long enough to read, so a fast start does not look like a glitch

export default function Home() {
  const [category, setCategory] = useState<Category | null>(null);
  const [session, setSession] = useState<Session>({ status: "idle", id: null });
  const headingRef = useRef<HTMLHeadingElement>(null);
  const sessionRef = useRef<string | null>(null);
  const pickToken = useRef(0);

  // Focus the heading after every screen change so keyboard and screen-reader users stay oriented.
  useEffect(() => {
    headingRef.current?.focus();
  }, [category, session.status]);

  // Delete the container when the tab closes or the page unmounts. (The server also closes idle sessions.)
  useEffect(() => {
    const release = () => {
      const id = sessionRef.current;
      sessionRef.current = null;
      if (id) closeSession(id);
    };
    // Both events: browsers differ in which one fires when a tab is closed or navigated away. Releasing twice is harmless.
    window.addEventListener("pagehide", release);
    window.addEventListener("beforeunload", release);
    return () => {
      window.removeEventListener("pagehide", release);
      window.removeEventListener("beforeunload", release);
      release();
    };
  }, []);

  function release() {
    const id = sessionRef.current;
    sessionRef.current = null;
    if (id) closeSession(id);
  }

  /** Picking a category opens this person's own private container. */
  async function choose(c: Category) {
    const token = ++pickToken.current;
    release();
    setCategory(c);
    setSession({ status: "opening", id: null });
    // Open the container and keep the screen up for a minimum time, side by side; wait for both.
    const [id] = await Promise.all([
      openSession().catch(() => null), // the checks still work without one, and the screen says so
      new Promise((resolve) => setTimeout(resolve, MIN_OPENING_MS)),
    ]);
    if (token !== pickToken.current) {
      if (id) closeSession(id); // they left while it was opening
      return;
    }
    sessionRef.current = id;
    setSession({ status: id ? "ready" : "none", id });
  }

  function back() {
    pickToken.current++;
    release();
    setCategory(null);
    setSession({ status: "idle", id: null });
  }

  const chosen = CATEGORIES.find((c) => c.id === category);

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-8 sm:px-6">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">TrustGuard</h1>
        <p className="mt-1 text-zinc-500">Checks whether the identity, the media and the context agree, and explains why.</p>
      </header>

      {!chosen && (
        <section className="mt-8" aria-labelledby="pick-title">
          <h2 id="pick-title" ref={headingRef} tabIndex={-1} className="text-xl font-semibold outline-none">
            What would you like to check?
          </h2>
          <div className="mt-4 grid gap-3">
            {CATEGORIES.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => choose(c.id)}
                className="rounded-lg border border-zinc-300 p-4 text-left transition hover:bg-zinc-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 dark:border-zinc-700 dark:hover:bg-zinc-900"
              >
                <span className="flex flex-wrap items-center gap-2">
                  <span className="text-base font-semibold">{c.title}</span>
                  <span
                    className={`rounded px-2 py-0.5 text-xs font-medium ${
                      c.ready
                        ? "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/50 dark:text-emerald-100"
                        : "bg-amber-100 text-amber-900 dark:bg-amber-900/50 dark:text-amber-100"
                    }`}
                  >
                    {c.status}
                  </span>
                </span>
                <span className="mt-1 block text-sm text-zinc-500">{c.blurb}</span>
              </button>
            ))}
          </div>
        </section>
      )}

      {chosen && session.status === "opening" && (
        <section className="mt-16 flex flex-col items-center gap-4 text-center" role="status" aria-live="polite">
          <Loader cellSize={20} />
          <h2 ref={headingRef} tabIndex={-1} className="text-lg font-semibold outline-none">
            Opening a private container…
          </h2>
          <p className="max-w-md text-sm text-zinc-500">
            This is your own throwaway environment. Files and email headers you check are read inside it, with no network and
            a read-only disk. It is deleted when you leave this screen.
          </p>
        </section>
      )}

      {chosen && session.status !== "opening" && (
        <div className="mt-6">
          <button type="button" onClick={back} className="text-sm text-zinc-500 underline underline-offset-2">
            ← Change category
          </button>
          <h2 ref={headingRef} tabIndex={-1} className="mt-2 text-xl font-semibold outline-none">
            {chosen.title}
          </h2>
          <p className="mt-2 flex items-start gap-2 text-xs text-zinc-500">
            <span
              className={`mt-0.5 inline-block size-2 shrink-0 rounded-full ${session.id ? "bg-emerald-500" : "bg-amber-500"}`}
              aria-hidden
            />
            <span>
              {session.id
                ? "Your private container is open. Files and email headers you check here are read inside it, with no network. It is deleted when you leave this screen, close the tab, or after 10 idle minutes. The AI model runs outside it."
                : "No sandbox container is available (Docker is not running or the image is missing), so files and headers are read directly by the server."}
            </span>
          </p>

          <div className="mt-4">
            {chosen.id === "phishing" && <PhishingCheck sessionId={session.id} />}

            {chosen.id === "document" && (
              <DocumentCheck
                apiBase={API}
                sessionId={session.id}
                heading="Upload a document"
                intro="Upload an invoice, letter or photo of one. TrustGuard reads what the file says about itself: which program made it, when, whether it was saved again afterwards. The file is read in memory and never stored."
              />
            )}

            {chosen.id === "persona" && (
              <div className="space-y-6">
                <DocumentCheck
                  apiBase={API}
                  sessionId={session.id}
                  heading="Check an image"
                  intro="Upload a photo, profile picture or screenshot. TrustGuard reads what the file says about itself: whether it names an AI image tool, carries AI-generation settings or content credentials, or was edited. The file is read in memory and never stored."
                  accept=".jpg,.jpeg,.png"
                  fileLabel="Image (JPG or PNG, up to 10 MB)"
                  showVendor={false}
                  buttonLabel="Check image"
                  uploadLabel="Upload image"
                />

                <Card title="Not available yet">
                  <ul className="list-disc space-y-1 pl-5 text-sm">
                    <li>Voice cloning detection</li>
                    <li>Video deepfake detection</li>
                    <li>Face and profile matching</li>
                  </ul>
                  <p className="mt-3 text-sm text-zinc-500">
                    These are not built in this version, and the image check above only reads metadata, which is easy to
                    remove. So no warning does not mean an image is real.
                  </p>
                  <p className="mt-3 text-sm font-medium">Until then, verify the person another way:</p>
                  <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
                    <li>Call them back on a number you already have, not one they gave you.</li>
                    <li>Ask a question only the real person could answer.</li>
                    <li>Ask for a live video call and have them say a phrase you choose.</li>
                    <li>Run a reverse image search on their photo.</li>
                  </ul>
                  <p className="mt-3 text-sm">
                    If they wrote to you, you can also{" "}
                    <button type="button" onClick={() => choose("phishing")} className="underline underline-offset-2">
                      check what they wrote
                    </button>
                    .
                  </p>
                </Card>
              </div>
            )}
          </div>
        </div>
      )}
    </main>
  );
}
