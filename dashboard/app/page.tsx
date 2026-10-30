import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import { Figure } from "@/components/docs/figure";
import GateScene from "@/components/docs/figures/home-1";
import { LampDot, Verdict, type Lamp } from "@/components/docs/verdict";

export const metadata: Metadata = { title: { absolute: "Release gate" } };

const SCENE_ALT =
  "Example 1, invoice reader, newer model snapshot: main 0.925, request 0.900, a drop of 2.5 points, pass; one case went from 1.00 to 0.75. Example 2, booking assistant, shorter system prompt: main 0.800, request 0.500, a drop of 30 points, block; the three cases where the assistant acts for someone other than the caller went from 1 to 0. Example 3, booking assistant, README and CI changes: unchanged, nothing ran. Example 4, support chat, typo fixes: main 0.700, request 0.600, a drop of 10 points, block. In the author's measurement, one unchanged version of a support agent scored between 0.4 and 0.7 on the same 10 cases over 11 runs, so a drop like this is most likely noise.";

const TERMS: [string, string][] = [
  ["Case", "One test input with the checks its answer must pass."],
  ["Version", "The app's config, its prompts and the repository's code."],
  ["Base and candidate", "The version on the target branch, and the version in the request."],
  ["Run", "One pass of a version over the cases."],
];

const ANSWERS: { lamp: Lamp; name: string; today: ReactNode; planned: ReactNode }[] = [
  {
    lamp: "go",
    name: "Pass",
    today: "The request's mean score is at most δ points below the base's, on one run per version.",
    planned: "Several runs show that the request loses no more than δ.",
  },
  {
    lamp: "stop",
    name: "Block",
    today: "The mean score drops by more than δ points, on one run per version.",
    planned: "Several runs show that the request loses more than δ.",
  },
  {
    lamp: "wait",
    name: "Not sure yet",
    today: null,
    planned:
      "When the runs cannot tell a loss of more than δ from noise, the gate says so instead of guessing, runs more, and if that is still not enough, leaves the decision to a person.",
  },
];

const CHECKS: [string, ReactNode][] = [
  [
    "Any app",
    "From one model call to an agent with tools in a conversation. The gate runs a Python adapter or any program that reads one JSON request and prints one JSON answer, so the app can be in any language.",
  ],
  [
    "Your cases and checks",
    "You write the test cases and say what to check: fields, text and numbers in the answer, and in the run's steps which tools were called, with which arguments, in which order, and how the world changed.",
  ],
  [
    "What counts as a change",
    <>
      A new prompt, model or parameter, and any change to the code git tracks, the lock file included, makes a new version, and
      both versions run. Documentation, CI, <Code>gate.yaml</Code> with its price files, the paths you list in its{" "}
      <Code>ignore</Code>, the test sets, other pipelines&apos; files and files git does not track do not count.
    </>,
  ],
  [
    "Only through cases",
    "The gate sees a change only where a case touches it: an edit no case exercises passes unseen, and a pass speaks for your cases, not for inputs your set does not have.",
  ],
  [
    "The list grows",
    <>
      Add your own check as a Python function (the <Code>function</Code> check), or run any program as the app.{" "}
      <A href="/docs/what-it-catches">What it catches</A> lists the kinds of changes, which checks see each one, and what is
      planned next.
    </>,
  ],
];

const PATHS: { reader: string; body: ReactNode }[] = [
  {
    reader: "I'm deciding whether to use it",
    body: (
      <>
        <A href="/docs/how-it-works">How it works</A> follows one pull request from start to end.{" "}
        <A href="/docs/how-it-decides">How it decides</A> covers noise, δ and the planned rule.{" "}
        <A href="/docs/what-it-catches">What it catches</A> lists the kinds of changes and how you add your own checks.{" "}
        <A href="/docs/limits">Limits and comparison</A> says what it does not do.
      </>
    ),
  },
  {
    reader: "I'm setting it up",
    body: (
      <>
        <A href="/docs/start">Get started</A> takes you to a first verdict in about ten minutes. Then{" "}
        <A href="/docs/write-tests">Write tests</A>, <A href="/docs/connect">Connect your app</A> and the{" "}
        <A href="/docs/reference">Reference</A>. It runs as a GitHub Action; on another CI, the{" "}
        <Code>llm-release-gate pr</Code> command does the work.
      </>
    ),
  },
  {
    reader: "I got a verdict on my pull request",
    body: (
      <>
        <A href="/docs/read-a-verdict">Read a verdict</A> says what each answer means and what to do next. The{" "}
        <A href="/docs/dashboard">Dashboard</A> shows every case of the run on both sides.
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
            You changed a prompt, a model or the code around a model call. A few tries by hand will not tell you whether the app
            got worse, because a model answers differently each time.
          </p>
          <p>
            <strong>Check every change to your LLM app against the version it would replace.</strong> On each pull request,
            llm-release-gate runs the version on your target branch (<Code>main</Code> in these examples) and the version in the
            request on the same test cases, scores both and posts the verdict as a comment on the request.
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
          Four pull requests on three made-up apps: an invoice reader (one model call that extracts fields), a booking
          assistant (an agent with tools) and a support chat (a dialog with a simulated customer). The apps, cases and numbers
          are examples. The comments have the exact form the gate writes.
        </p>
        <Figure
          framed={false}
          alt={SCENE_ALT}
          caption="Four example pull requests on made-up apps. Where a request changes the app, each version runs the same ten cases once; the gate compares the mean scores and blocks a drop of more than 5 points (today's rule). Where it does not, nothing runs."
        >
          <GateScene />
        </Figure>
        <dl className="mt-10 grid gap-x-8 gap-y-5 border-t border-line pt-6 sm:grid-cols-2 lg:grid-cols-4">
          {TERMS.map(([term, definition]) => (
            <div key={term}>
              <dt className="font-bold">{term}</dt>
              <dd className="mt-1 text-ink-2">{definition}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section aria-labelledby="answers" className="mt-24 sm:mt-32">
        <H2 id="answers">Three answers</H2>
        <p className="mt-4 max-w-[64ch] text-lg text-ink-2">The barrier has three lamps. Today two of them work; the third is planned.</p>
        <div className="mt-8 overflow-hidden rounded-lg border border-line bg-panel">
          <div className="hidden grid-cols-[13rem_1fr_1fr] border-b border-line px-6 py-2.5 text-sm text-ink-2 md:grid">
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
              <strong>δ</strong> (delta) is the loss you accept, 5 points by default, set in <Code>gate.yaml</Code>. The gate
              reads its rules from the target branch, so editing them in a request does not loosen that request&apos;s own gate.
            </p>
            <p>
              Today&apos;s rule runs each version once, so noise alone can block a request, as in example 4. The planned rule
              runs each version several times, puts an interval around the difference and compares the interval with δ.{" "}
              <A href="/docs/how-it-decides">How it decides</A> explains it on the author&apos;s noise measurements. How often
              the gate is wrong will be measured in experiments that have not run yet, so this site gives no error rates.
            </p>
            <p>A block fails the CI job. Until you make the job a required check, it only advises.</p>
          </div>
          <div className="max-w-[64ch]">
            <p className="text-ink-2">The comment can also say:</p>
            <dl className="mt-3 space-y-3">
              {(
                [
                  ["budget fail", "The score passed, a cost or latency limit did not."],
                  ["unchanged", "Nothing ran."],
                  ["no base version", "A pipeline new in this request runs alone and passes."],
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
            <p className="mt-4 text-ink-2">
              Two more outcomes have no title of their own. A request that removes or renames a pipeline in{" "}
              <Code>gate.yaml</Code> fails the job as inconclusive (exit code 11, which the planned rule keeps for &ldquo;not sure
              yet&rdquo;), and the other pipelines&apos; comments say why. A request from a fork gets no comment: GitHub gives it
              no secrets, so no API key; the job fails as <Code>not checked</Code>, and the job&apos;s summary says why.{" "}
              <A href="/docs/read-a-verdict">Read a verdict</A> covers each one.
            </p>
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
          Today the gate&apos;s repository is private and only its owner&apos;s repositories can use it; the public release is
          planned.
        </p>
      </section>

      <section aria-labelledby="not" className="mt-24 sm:mt-32">
        <H2 id="not">What it is not</H2>
        <p className="mt-4 max-w-[68ch] text-lg">
          It does not grade text with a model: every built-in check is code (a model-graded check you turn on yourself is
          planned, without a date). It is not a benchmark for choosing a model. It is not a security control: it runs the
          request&apos;s code, so it catches mistakes, not a hostile author. <A href="/docs/limits">Limits and comparison</A> says
          more.
        </p>
      </section>
    </main>
  );
}
