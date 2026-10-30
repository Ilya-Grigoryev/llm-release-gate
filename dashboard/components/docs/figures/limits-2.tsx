import { FigureHead, Key } from "./kit";

const Tip = () => (
  <svg aria-hidden viewBox="0 0 8 12" className="-ml-1.5 h-3 w-2 shrink-0">
    <path d="M1.5 1.5 6.5 6l-5 4.5" fill="none" stroke="var(--ink-3)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

/** An arrow from the base bar to the candidate bar; `className` places it. */
const Diff = ({ className }: { className: string }) => (
  <span aria-hidden className={`absolute top-1/2 flex items-center ${className}`}>
    <span className="h-0 flex-1 border-t-[1.5px] border-ink-3" />
    <Tip />
  </span>
);

const bar = "absolute bottom-0 h-full w-4 rounded-t-sm";

/** A time axis with the provider's band, the base bar and the candidate bar. */
function Panel({ title, together }: { title: string; together: boolean }) {
  return (
    <div className="rounded-md border border-line p-3">
      <p className="font-bold">{title}</p>
      <div className="mt-3">
        <div className="relative mr-10">
          <span aria-hidden className={`absolute inset-y-0 bg-paper ${together ? "inset-x-[24%]" : "inset-x-[30%]"}`} />
          <p className={`relative py-1.5 text-center text-sm leading-tight text-ink-2 ${together ? "px-[24%]" : "px-[30%]"}`}>
            the provider&apos;s servers may change
          </p>
          <p className="relative pt-2 pb-1 text-center text-sm leading-tight">{together ? "change + noise" : "change + drift + noise"}</p>
          <div className="relative h-14">
            {together ? (
              <>
                <span className={`${bar} left-[calc(50%-1.75rem)] bg-arm-base`} />
                <Diff className="left-[calc(50%-0.7rem)] w-[1.4rem]" />
                <span className={`${bar} left-[calc(50%+0.75rem)] bg-arm-cand`} />
              </>
            ) : (
              <>
                <span className={`${bar} left-[6%] bg-arm-base`} />
                <Diff className="right-[calc(6%+1.25rem)] left-[calc(6%+1.25rem)]" />
                <span className={`${bar} right-[6%] bg-arm-cand`} />
              </>
            )}
          </div>
        </div>
        <div className="flex items-center text-sm text-ink-2">
          <span aria-hidden className="h-0 flex-1 border-t-[1.5px] border-ink-3" />
          <Tip />
          <span className="ml-1.5">time</span>
        </div>
        <div className="relative mr-10 h-6 pt-1 text-sm whitespace-nowrap text-ink-2">
          {together ? (
            <span className="absolute left-1/2 -translate-x-1/2">this pull request</span>
          ) : (
            <>
              <span className="absolute left-[6%]">last week</span>
              <span className="absolute right-[6%]">this pull request</span>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function Limits2({}: { alt: string }) {
  return (
    <div className="@container">
      <FigureHead tag="Illustration">
        <Key items={[{ color: "var(--base)", label: "base (main)" }, { color: "var(--cand)", label: "candidate (the request)" }]} />
      </FigureHead>
      <div className="grid gap-4 @xl:grid-cols-2">
        <Panel title="Base from an earlier run" together={false} />
        <Panel title="Base in the same job" together />
      </div>
    </div>
  );
}
