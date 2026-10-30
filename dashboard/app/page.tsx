import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import { Figure } from "@/components/docs/figure";
import GateScene from "@/components/docs/figures/home-1";
import { LampDot, Verdict, type Lamp } from "@/components/docs/verdict";

export const metadata: Metadata = { title: { absolute: "Release gate" } };

const SCENE_ALT =
  "Example 1, invoice reader, newer model snapshot: main 0.925, request 0.900, a drop of 2.5 points, pass; one case went from 1.00 to 0.75. Example 2, booking assistant, shorter system prompt: main 0.800, request 0.500, a drop of 30 points, block; the three cases where the assistant acts for someone other than the caller went from 1 to 0. Example 3, booking assistant, README and CI changes: unchanged, nothing ran. Example 4, support chat, typo fixes: main 0.700, request 0.600, a drop of 10 points, block. In the author's measurement, one unchanged version of a support agent scored between 0.4 and 0.7 on the same 10 cases over 11 runs, so a drop like this is most likely noise.";

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

const CHECKS: [string, ReactNode][] = [
  ["Any app", "A Python adapter, or any program that reads one JSON request and prints one JSON answer."],
  [
    "Your cases and checks",
    <>
      Fields, text and numbers in the answer; tool calls, their arguments and order, and state changes in the run&apos;s steps.
      You can add your own check in Python. <A href="/docs/what-it-catches">What it catches</A> lists which checks see which
      changes.
    </>,
  ],
  [
    "What counts as a change",
    <>
      A new prompt, model or parameter, or any change to the code git tracks.{" "}
      <A href="/docs/how-it-works#what-a-version-is">What a version is</A> lists what does not count.
    </>,
  ],
  ["Only through cases", "An edit no case exercises passes unseen."],
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

/** The docs' home: the question, the gate scene, the three answers, what it checks and where to go. */
export default function Home() {
  return (
    <main className="mx-auto w-full max-w-[76rem] flex-1 px-4 pt-14 pb-28 sm:px-6 sm:pt-20 lg:px-10">
      <section aria-labelledby="question">
        <h1 id="question" className="max-w-[19ch] font-display text-[2.6rem] leading-[0.98] font-extrabold tracking-[-0.03em] text-balance sm:text-[clamp(3.5rem,6.4vw,5.5rem)]">
          Did this pull request make your LLM app worse?
        </h1>
        <div className="mt-8 grid max-w-[62rem] gap-x-12 gap-y-5 text-lg sm:mt-10 md:grid-cols-2 md:leading-relaxed">
          <p className="text-ink-2">
            A model answers differently each time, so a few tries by hand will not tell you whether a change made your app
            worse.
          </p>
          <p>
            <strong>Check every change to your LLM app against the version it would replace.</strong> On each pull request,
            llm-release-gate runs your target branch&apos;s version (<Code>main</Code> here) and the request&apos;s on the same
            test cases and posts the verdict as a comment.
          </p>
        </div>
        <div className="mt-8 flex flex-wrap gap-3">
          <Link href="/docs/start" className="rounded-md bg-ink px-5 py-2.5 font-bold text-paper hover:bg-ink/85">
            Get started
          </Link>
          <Link href="/docs/how-it-works" className="rounded-md border border-ink-3/50 px-5 py-2.5 font-bold hover:border-ink">
            How it works
          </Link>
        </div>
      </section>

      <section aria-labelledby="examples" className="mt-20 sm:mt-24">
        <h2 id="examples" className="sr-only">
          Four example pull requests
        </h2>
        <p className="mb-5 max-w-[68ch] text-ink-2">
          Four pull requests on three made-up apps: an invoice reader (one model call), a booking assistant (an agent with
          tools) and a support chat (a dialog). <A href="/docs/reference#terms">Reference</A> defines the terms.
        </p>
        <Figure
          framed={false}
          alt={SCENE_ALT}
          caption="Where a request changes the app, each version runs the same ten cases once; the gate compares the mean scores and blocks a drop of more than 5 points (today's rule). Where it does not, nothing runs."
        >
          <GateScene />
        </Figure>
      </section>

      <section aria-labelledby="answers" className="mt-24 sm:mt-32">
        <H2 id="answers">Three answers</H2>
        <div className="mt-8 overflow-hidden rounded-lg border border-line bg-panel">
          <div className="hidden grid-cols-[13rem_1fr_1fr] gap-x-8 border-b border-line px-6 py-2.5 text-sm text-ink-2 md:grid">
            <span>Answer</span>
            <span>Today</span>
            <span>Planned</span>
          </div>
          {ANSWERS.map(({ lamp, name, today, planned }) => (
            <div key={name} className="grid gap-x-8 gap-y-2 border-line px-5 py-5 not-last:border-b sm:px-6 md:grid-cols-[13rem_1fr_1fr]">
              <div className="flex items-center gap-3 self-start">
                <LampDot lamp={lamp} className="size-4" />
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

        <div className="mt-8 grid gap-x-12 gap-y-6 lg:grid-cols-2">
          <div className="max-w-[64ch] space-y-4">
            <p>
              <strong>δ</strong> (delta) is the loss you accept, 5 points by default, set in <Code>gate.yaml</Code> on the
              target branch.
            </p>
            <p>
              Today&apos;s rule runs each version once, so noise alone can block a request, as in example 4;{" "}
              <A href="/docs/how-it-decides">How it decides</A> has the author&apos;s noise measurements. There are no error
              rates yet: the experiments have not run.
            </p>
            <p>A block fails the CI job; until the job is a required check, it only advises.</p>
          </div>
          <div className="max-w-[64ch]">
            <p className="text-ink-2">The comment can also say:</p>
            <dl className="mt-3 space-y-3">
              {(
                [
                  ["budget fail", "The score passed, a cost or latency limit did not."],
                  ["unchanged", "Nothing ran."],
                  ["no base version", "A new pipeline runs alone and passes."],
                  ["infra error", "The runs could not be compared, or the tool failed."],
                ] as const
              ).map(([kind, text]) => (
                <div key={kind} className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <dt>
                    <Verdict kind={kind} />
                  </dt>
                  <dd className="min-w-[16rem] flex-1 text-ink-2">{text}</dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      </section>

      <section aria-labelledby="checks" className="mt-24 sm:mt-32">
        <H2 id="checks">What it checks</H2>
        <dl className="mt-8 grid gap-x-12 gap-y-8 md:grid-cols-2">
          {CHECKS.map(([term, text]) => (
            <div key={term} className="max-w-[60ch] border-t-2 border-ink pt-3">
              <dt className="font-display text-xl font-bold">{term}</dt>
              <dd className="mt-1.5 text-ink-2">{text}</dd>
            </div>
          ))}
        </dl>
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

      <section aria-labelledby="not" className="mt-24 sm:mt-32">
        <H2 id="not">What it is not</H2>
        <p className="mt-4 max-w-[68ch] text-lg">
          Every built-in check is code, not a model grading text. It is not a benchmark for choosing a model, nor a security
          control: it runs the request&apos;s code, so it catches mistakes, not a hostile author.
        </p>
      </section>
    </main>
  );
}
