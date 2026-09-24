"use client";

import { useEffect, useRef, useState } from "react";
import { Card } from "./components";
import { DocumentCheck } from "./document-check";
import { API } from "./lib";
import { PhishingCheck } from "./phishing-check";

type Category = "phishing" | "document" | "persona";

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

export default function Home() {
  const [category, setCategory] = useState<Category | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    headingRef.current?.focus(); // keep keyboard and screen-reader users oriented after every screen change
  }, [category]);

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
                onClick={() => setCategory(c.id)}
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

      {chosen && (
        <div className="mt-6">
          <button
            type="button"
            onClick={() => setCategory(null)}
            className="text-sm text-zinc-500 underline underline-offset-2"
          >
            ← Change category
          </button>
          <h2 ref={headingRef} tabIndex={-1} className="mt-2 text-xl font-semibold outline-none">
            {chosen.title}
          </h2>

          <div className="mt-4">
            {chosen.id === "phishing" && <PhishingCheck />}

            {chosen.id === "document" && (
              <DocumentCheck
                apiBase={API}
                heading="Upload a document"
                intro="Upload an invoice, letter or photo of one. TrustGuard reads what the file says about itself: which program made it, when, whether it was saved again afterwards. The file is read in memory and never stored."
              />
            )}

            {chosen.id === "persona" && (
              <div className="space-y-6">
                <DocumentCheck
                  apiBase={API}
                  heading="Check an image"
                  intro="Upload a photo, profile picture or screenshot. TrustGuard reads what the file says about itself: whether it names an AI image tool, carries AI-generation settings or content credentials, or was edited. The file is read in memory and never stored."
                  accept=".jpg,.jpeg,.png"
                  fileLabel="Image (JPG or PNG, up to 10 MB)"
                  showVendor={false}
                  buttonLabel="Check image"
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
                    <button type="button" onClick={() => setCategory("phishing")} className="underline underline-offset-2">
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
