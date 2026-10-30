import type { ReactNode } from "react";
import { FigureHead, LampDot } from "./kit";

/* One track in ink: down the left edge while the figure is narrow, left to right from @lg. */

const M = ({ children }: { children: ReactNode }) => <span className="font-mono text-[0.9em]">{children}</span>;

function Stop({ mark, last = false, title, children }: { mark: ReactNode; last?: boolean; title: ReactNode; children: ReactNode }) {
  return (
    <li className="relative mt-0 pb-6 pl-10 last:pb-0 @lg:pt-10 @lg:pr-4 @lg:pb-0 @lg:pl-0">
      {!last && (
        <span
          aria-hidden
          className="absolute top-0 bottom-0 left-[13px] w-0.5 bg-ink @lg:top-[13px] @lg:right-0 @lg:bottom-auto @lg:left-0 @lg:h-0.5 @lg:w-auto"
        />
      )}
      <span className="absolute top-0 left-0">{mark}</span>
      <p className="leading-snug font-bold">{title}</p>
      <div className="mt-1 space-y-2 text-sm leading-snug text-ink-2">{children}</div>
    </li>
  );
}

const Post = ({ n }: { n: number }) => (
  <span className="grid size-7 place-items-center rounded-full border-2 border-ink bg-panel font-mono text-sm font-bold">{n}</span>
);

const Out = ({ children }: { children: ReactNode }) => (
  <p className="border-t border-line pt-2">
    <span className="font-bold text-ink">Falls out here:</span> {children}
  </p>
);

export default function Limits1({}: { alt: string }) {
  return (
    <div className="@container">
      <FigureHead tag="Illustration" />
      <ol role="list" className="grid list-none pl-0 @lg:grid-cols-[auto_repeat(3,minmax(0,1fr))]">
        <li className="relative flex h-11 gap-2 pl-10 @lg:h-7 @lg:items-center @lg:pl-0">
          <span aria-hidden className="absolute top-[9px] left-[9px] size-2.5 rounded-full bg-ink @lg:static" />
          <span aria-hidden className="absolute top-[14px] bottom-0 left-[13px] w-0.5 bg-ink @lg:hidden" />
          A change
          <span aria-hidden className="hidden h-0.5 min-w-4 flex-1 bg-ink @lg:block" />
        </li>
        <Stop mark={<Post n={1} />} title="Is it part of the version?">
          <p>config, prompt bytes, code as git sees it</p>
          <Out>
            a README, CI, <M>gate.yaml</M>, ignored paths, data outside the repository.
          </Out>
        </Stop>
        <Stop mark={<Post n={2} />} title="Does a case exercise it?">
          <Out>
            the refund limit <M>€30</M> → <M>€40</M> when no case asks for an amount between them.
          </Out>
        </Stop>
        <Stop
          last
          mark={
            <span className="flex w-7 flex-col items-center gap-1 rounded-md border-2 border-ink bg-panel py-1.5 @lg:h-7 @lg:w-auto @lg:flex-row @lg:px-1.5 @lg:py-0">
              <LampDot lamp="neutral" className="size-2.5" />
              <LampDot lamp="neutral" className="size-2.5" />
              <LampDot lamp="neutral" className="size-2.5" />
            </span>
          }
          title={
            <>
              The barrier: is the drop larger than <M>delta</M>?
            </>
          }
        >
          <Out>
            one broken case among <M>20</M> (exactly <M>5</M> points).
          </Out>
          <p className="rounded-md border border-line px-2 py-1.5">
            <span className="font-bold text-ink">Today:</span> one run per version, so noise can push a drop over or under{" "}
            <M>delta</M>. <span className="font-bold text-ink">Planned:</span> repeated runs and an interval.
          </p>
        </Stop>
      </ol>
    </div>
  );
}
