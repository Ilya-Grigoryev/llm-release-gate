import { useId, type ReactNode } from "react";

/**
 * A drawing, chart or interactive figure. `caption` is the one sentence that says what to see in it; `alt` describes
 * it for readers who cannot see it. `wide` lets it use the content column's full width instead of the text measure.
 */
export function Figure({
  caption,
  alt,
  wide = false,
  framed = true,
  children,
}: {
  caption: ReactNode;
  alt: string;
  wide?: boolean;
  framed?: boolean;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <figure className={wide ? "wide" : undefined} aria-describedby={id}>
      <div className={framed ? "overflow-hidden rounded-md border border-line bg-panel p-4 sm:p-6" : undefined}>{children}</div>
      <p id={id} className="sr-only">
        {alt}
      </p>
      <figcaption className="mt-2.5 text-base text-ink-2">{caption}</figcaption>
    </figure>
  );
}
