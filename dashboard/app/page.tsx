import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import { Figure } from "@/components/docs/figure";
import GateScene from "@/components/docs/figures/home-1";
import { LampDot, type Lamp } from "@/components/docs/verdict";
import { HeroIntro, HeroRails, LampsReveal } from "@/components/home/motion";

export const metadata: Metadata = { title: { absolute: "Release gate" } };

const SCENE_ALT =
  "Two trains, main and the request, pass the same cases, then their tracks join into one. When the request passes, its train takes the joined track and a barrier stops main's; when it is blocked, it is the other way round. Example 1, invoice reader, newer model snapshot: main 0.925, request 0.900, a drop of 2.5 points, pass; one case went from 1.00 to 0.75. Example 2, booking assistant, shorter system prompt: main 0.800, request 0.500, a drop of 30 points, block; the three cases where the assistant acts for someone other than the caller went from 1 to 0. Example 3, booking assistant, README and CI changes: unchanged, nothing ran. Example 4, support chat, typo fixes: main 0.700, request 0.600, a drop of 10 points, block. In the author's measurement, one unchanged version of a support agent scored between 0.4 and 0.7 on the same 10 cases over 11 runs, so a drop like this is most likely noise.";

const ANSWERS: { lamp: Lamp; name: string; today: ReactNode; planned: ReactNode }[] = [
  {
    lamp: "go",
    name: "Pass",
    today: "The mean score is at most δ points below the base's, on one run per version.",
    planned: "Several runs show a loss of no more than δ.",
  },
  {
    lamp: "stop",
    name: "Block",
    today: "The mean score drops by more than δ points, on one run per version.",
    planned: "Several runs show a loss of more than δ.",
  },
  {
    lamp: "wait",
    name: "Not sure yet",
    today: null,
    planned: "The gate cannot tell a loss of more than δ from noise, runs more, and if still unsure, leaves the decision to a person.",
  },
];

const PATHS: { reader: string; body: ReactNode }[] = [
  {
    reader: "I'm deciding whether to use it",
    body: (
      <>
        <A href="/docs/how-it-works">How it works</A> follows one pull request; <A href="/docs/how-it-decides">How it decides</A>{" "}
        covers noise and δ; <A href="/docs/limits">Limits and comparison</A> says what it does not do.
      </>
    ),
  },
  {
    reader: "I'm setting it up",
    body: (
      <>
        <A href="/docs/start">Get started</A> takes you to a first verdict in about ten minutes, then{" "}
        <A href="/docs/write-tests">Write tests</A>, <A href="/docs/connect">Connect your app</A> and the{" "}
        <A href="/docs/reference">Reference</A>.
      </>
    ),
  },
  {
    reader: "I got a verdict on my pull request",
    body: (
      <>
        <A href="/docs/read-a-verdict">Read a verdict</A> says what to do next; the <A href="/docs/dashboard">Dashboard</A> shows
        every case on both sides.
      </>
    ),
  },
];

function Code({ children }: { children: ReactNode }) {
  return <code className="rounded-sm bg-ink/[0.06] px-1 py-px font-mono text-[0.88em]">{children}</code>;
}

function A({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link href={href} className="font-bold text-ink underline decoration-ink-3/60 decoration-1 underline-offset-[3px] hover:decoration-ink">
      {children}
    </Link>
  );
}

function H2({ id, children }: { id: string; children: ReactNode }) {
  return (
    <h2 id={id} className="scroll-mt-20 font-display text-[1.75rem] leading-tight font-bold tracking-[-0.02em] sm:text-[2.125rem]">
      {children}
    </h2>
  );
}

/**
 * The site's home page, open to everyone: the question fills the first screen; below it the trains through the gate, the
 * three answers and where to go.
 */
export default function Home() {
  return (
    <main className="flex-1 pb-28">
      <HeroIntro>
        <section
          aria-labelledby="question"
          className="relative isolate flex min-h-[calc(100svh-var(--header))] flex-col items-center justify-center overflow-hidden px-4 pt-10 pb-[26vh] text-center sm:px-6"
        >
          <h1
            id="question"
            data-intro
            className="max-w-[22ch] font-display text-[2.75rem] leading-[0.98] font-extrabold tracking-[-0.03em] text-balance sm:text-[clamp(3.5rem,6.6vw,6rem)]"
          >
            Did this pull request make your LLM app worse?
          </h1>
          <p data-intro className="mt-7 max-w-[56ch] text-lg text-ink-2 md:text-xl md:leading-relaxed">
            On every pull request, llm-release-gate runs the version on <Code>main</Code> and the version in the request on the
            same test cases and posts the verdict as a comment.
          </p>
          <div data-intro className="mt-8 flex flex-wrap justify-center gap-3">
            <Link href="/docs/start" className="rounded-md bg-ink px-5 py-2.5 font-bold text-paper hover:bg-ink/85">
              Get started
            </Link>
            <Link href="/docs/how-it-works" className="rounded-md border border-ink-3/50 px-5 py-2.5 font-bold hover:border-ink">
              How it works
            </Link>
          </div>
          <HeroRails />
          <a data-intro href="#examples" className="absolute bottom-5 flex flex-col items-center gap-1 text-sm text-ink-2 hover:text-ink">
            Four example pull requests
            <svg data-cue aria-hidden viewBox="0 0 16 16" className="size-4">
              <path d="M3 6l5 5 5-5" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </a>
        </section>
      </HeroIntro>

      <div className="mx-auto w-full max-w-[76rem] px-4 sm:px-6 lg:px-10">
        <section aria-labelledby="examples" className="scroll-mt-20 pt-16 sm:pt-20">
          <H2 id="examples">Four example pull requests</H2>
          <div className="mt-8">
            <Figure
              framed={false}
              alt={SCENE_ALT}
              caption="The pull requests are made up. Where one changes the app, each version runs the same ten cases once, and the gate blocks a drop in the mean score of more than 5 points (today's rule)."
            >
              <GateScene />
            </Figure>
          </div>
        </section>

        <section aria-labelledby="answers" className="mt-24 sm:mt-32">
          <H2 id="answers">Three answers</H2>
          <LampsReveal>
            <div className="mt-8 overflow-hidden rounded-lg border border-line bg-panel">
              <div className="hidden grid-cols-[13rem_1fr_1fr] gap-x-8 border-b border-line px-6 py-2.5 text-sm text-ink-2 md:grid">
                <span>Answer</span>
                <span>Today</span>
                <span>Planned</span>
              </div>
              {ANSWERS.map(({ lamp, name, today, planned }) => (
                <div key={name} className="grid gap-x-8 gap-y-2 border-line px-5 py-5 not-last:border-b sm:px-6 md:grid-cols-[13rem_1fr_1fr]">
                  <div className="flex items-center gap-3 self-start">
                    <span data-lamp className="inline-flex">
                      <LampDot lamp={lamp} className="size-4" />
                    </span>
                    <span className="font-display text-xl font-bold">{name}</span>
                  </div>
                  <p className={today ? "" : "text-ink-3"}>
                    <span className="mr-1.5 text-sm text-ink-2 md:hidden">Today:</span>
                    {today ?? "Not yet."}
                  </p>
                  <p className="text-ink-2">
                    <span className="mr-1.5 text-sm md:hidden">Planned:</span>
                    {planned}
                  </p>
                </div>
              ))}
            </div>
          </LampsReveal>
          <p className="mt-6 max-w-[68ch]">
            <strong>δ</strong> (delta) is the loss you accept, 5 points by default, set in <Code>gate.yaml</Code> on the target
            branch. Today&apos;s rule runs each version once, so noise alone can block a request, as in the support chat example;{" "}
            <A href="/docs/how-it-decides">How it decides</A> shows the author&apos;s measurement.
          </p>
        </section>

        <section aria-labelledby="where" className="mt-24 sm:mt-32">
          <H2 id="where">Where to go</H2>
          <div className="mt-8 grid gap-4 md:grid-cols-3">
            {PATHS.map(({ reader, body }) => (
              <div key={reader} className="rounded-lg border border-line bg-panel p-5 sm:p-6">
                <h3 className="font-display text-xl leading-snug font-bold">{reader}</h3>
                <p className="mt-3 text-ink-2">{body}</p>
              </div>
            ))}
          </div>
          <p className="mt-5 max-w-[68ch] text-ink-2">
            Today the gate&apos;s repository is private and only its owner&apos;s repositories can use it; a public release is
            planned.
          </p>
        </section>
      </div>
    </main>
  );
}
