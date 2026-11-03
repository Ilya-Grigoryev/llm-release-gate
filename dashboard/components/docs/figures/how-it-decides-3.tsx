import type { ReactNode } from "react";
import { Arrow, FigureHead, LampDot, Node, type Lamp } from "./kit";

/*
 * Top to bottom. From @lg the three outcomes sit side by side, and a rail in a fourth column carries "run more" back
 * up to the interval; when the figure stacks, an up arrow under "run more" says the same.
 */

const Said = ({ lamp, children }: { lamp: Lamp; children: ReactNode }) => (
  <span className="inline-flex items-center gap-2">
    <LampDot lamp={lamp} />
    {children}
  </span>
);

const Head = ({ className }: { className: string }) => (
  <svg aria-hidden viewBox="0 0 24 24" className={`size-5 shrink-0 ${className}`}>
    <path d="M3 12h16M13 6l6 6-6 6" fill="none" stroke="var(--ink-3)" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

/** One of the three exits: right off the bracket when the figure stacks, down from the question when it is wide. */
function Outcome({ edge, lamp, word, col, children }: { edge: string; lamp: Lamp; word: string; col: string; children?: ReactNode }) {
  return (
    <div className={`flex flex-col @lg:row-start-6 ${col}`}>
      <span className="flex items-center gap-1 py-1 text-sm leading-tight text-ink-2 @lg:flex-col @lg:text-center">
        <Head className="@lg:rotate-90" />
        {edge}
      </span>
      <Node title={<Said lamp={lamp}>{word}</Said>}>{children}</Node>
    </div>
  );
}

const rail = "absolute border-ink-3";
const centre = "@lg:col-[1/4] @lg:mx-auto @lg:w-full @lg:max-w-sm";

export default function HowItDecides3({}: { alt: string }) {
  return (
    <div className="@container">
      <FigureHead tag="The betting rule; running more on its own is planned" />
      <div className="grid @lg:grid-cols-[repeat(3,minmax(0,1fr))_6.5rem] @lg:gap-x-3">
        <Node title="Runs of both versions on the same cases" className={`${centre} @lg:row-start-1`} />
        <div className="@lg:col-[1/4] @lg:row-start-2">
          <Arrow down />
        </div>
        <div className="@lg:col-[1/4] @lg:row-start-3 @lg:flex">
          <span className="hidden flex-1 @lg:block" />
          <Node title="Interval around the difference" className="@lg:w-full @lg:max-w-sm">
            candidate − base
          </Node>
          <span aria-hidden className="relative hidden flex-1 @lg:block">
            <span className={`${rail} inset-x-0 top-1/2 border-t-[1.5px]`} />
            <svg viewBox="0 0 8 12" className="absolute top-1/2 left-0 h-3 w-2 -translate-y-1/2">
              <path d="M6.5 1.5 1.5 6l5 4.5" fill="none" stroke="var(--ink-3)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
        </div>
        <div className="@lg:col-[1/4] @lg:row-start-4">
          <Arrow down />
        </div>
        <Node title="Where does the interval lie against −δ?" className={`${centre} @lg:row-start-5`} />

        <div className="my-1 flex flex-col gap-1 border-l-[1.5px] border-ink-3 pl-1 @lg:contents">
          <Outcome edge="whole interval above −δ" lamp="go" word="pass" col="@lg:col-start-1">
            A real loss smaller than δ: pass with a warning.
          </Outcome>
          <Outcome edge="whole interval below −δ" lamp="stop" word="block" col="@lg:col-start-2" />
          <Outcome edge="reaches across −δ" lamp="wait" word="not sure yet" col="@lg:col-start-3" />
        </div>
        <div className="@lg:col-start-3 @lg:row-start-7">
          <Arrow down />
        </div>
        <Node title="Run more" className="@lg:col-start-3 @lg:row-start-8 @lg:self-center" />
        <p className="flex items-center justify-center gap-1 py-1 text-sm text-ink-2 @lg:hidden">
          <Head className="-rotate-90" />
          back to the interval, up to the maximum number of runs
        </p>
        <div className="@lg:col-start-3 @lg:row-start-9">
          <Arrow down label="still not sure at the maximum" />
        </div>
        <Node title="Red until a person approves the merge" className="@lg:col-start-3 @lg:row-start-10" />

        {/* The rail back to the interval, wide layout only. */}
        <span aria-hidden className="relative hidden @lg:col-start-4 @lg:row-start-3 @lg:block">
          <span className={`${rail} top-1/2 -left-3 w-6 border-t-[1.5px]`} />
          <span className={`${rail} top-1/2 bottom-0 left-3 border-l-[1.5px]`} />
        </span>
        <span className="relative hidden @lg:col-start-4 @lg:row-[4/8] @lg:block">
          <span aria-hidden className={`${rail} inset-y-0 left-3 border-l-[1.5px]`} />
          <span className="absolute top-1/2 right-0 left-5 -translate-y-1/2 text-sm leading-tight text-ink-2">
            up to the maximum number of runs
          </span>
        </span>
        <span aria-hidden className="relative hidden @lg:col-start-4 @lg:row-start-8 @lg:block">
          <span className={`${rail} top-0 bottom-1/2 left-3 border-l-[1.5px]`} />
          <span className={`${rail} top-1/2 -left-3 w-6 border-t-[1.5px]`} />
        </span>
      </div>
    </div>
  );
}
