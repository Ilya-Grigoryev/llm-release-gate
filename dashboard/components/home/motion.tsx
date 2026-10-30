"use client";

import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { SplitText } from "gsap/SplitText";
import { useId, useRef, type ReactNode } from "react";

gsap.registerPlugin(useGSAP, ScrollTrigger, SplitText);

const still = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

/**
 * The home page's opening, once on load: the headline's words rise in, then the other parts marked `data-intro`, while
 * the rails draw in; the cue to scroll bobs. globals.css hides those parts until this runs.
 */
export function HeroIntro({ children }: { children: ReactNode }) {
  const root = useRef<HTMLDivElement>(null);
  useGSAP(
    () => {
      const parts = gsap.utils.toArray<HTMLElement>("[data-intro]", root.current);
      gsap.set(parts, { opacity: 1, animation: "none" });
      const h1 = root.current?.querySelector("h1");
      if (still() || !h1) return;
      const split = SplitText.create(h1, { type: "words" });
      const rails = parts.filter((p) => p.matches("[data-rails]"));
      gsap
        .timeline({ onComplete: () => split.revert() })
        .from(split.words, { yPercent: 70, opacity: 0, duration: 0.8, ease: "power3.out", stagger: 0.06 })
        .from(
          parts.filter((p) => p !== h1 && !rails.includes(p)),
          { y: 14, opacity: 0, duration: 0.6, ease: "power2.out", stagger: 0.1 },
          "-=0.45",
        )
        .fromTo(
          gsap.utils.toArray("[data-reveal]", root.current),
          { attr: { width: 0 } },
          { attr: { width: 1440 }, duration: 1.6, ease: "power2.inOut" },
          0.3,
        );
      gsap.to("[data-cue]", { y: 4, duration: 0.9, ease: "sine.inOut", yoyo: true, repeat: -1, delay: 2 });
    },
    { scope: root },
  );
  return <div ref={root}>{children}</div>;
}

/*
 * The first screen's backdrop: main's rail and the request's run across the bottom and join into one, as in the scene
 * further down. Drawn on 1440 × 240; HeroIntro draws it in from the left.
 */
const HERO_RAILS = {
  base: "M-20 70H860C960 70 980 130 1080 130",
  cand: "M-20 190H860C960 190 980 130 1080 130",
  join: "M1080 130H1460",
};

export function HeroRails() {
  const uid = useId().replace(/[^\w-]/g, "");
  return (
    <svg
      data-intro
      data-rails
      aria-hidden
      viewBox="0 0 1440 240"
      preserveAspectRatio="xMaxYMax slice"
      className="pointer-events-none absolute inset-x-0 bottom-[7vh] -z-10 h-[24vh] w-full"
    >
      <clipPath id={`${uid}-reveal`}>
        <rect data-reveal width="1440" height="240" />
      </clipPath>
      <g clipPath={`url(#${uid}-reveal)`} fill="none">
        {Object.entries(HERO_RAILS).map(([arm, d]) => (
          <g key={arm}>
            <path d={d} transform="translate(0 3)" stroke="var(--ink-3)" strokeOpacity="0.22" strokeWidth="10" strokeDasharray="3 15" />
            <path d={d} stroke={arm === "join" ? "var(--ink-3)" : `var(--${arm})`} strokeOpacity="0.5" strokeWidth="2.5" />
          </g>
        ))}
      </g>
    </svg>
  );
}

/** Lights the lamps marked `data-lamp` one after another when they scroll into view. */
export function LampsReveal({ children }: { children: ReactNode }) {
  const root = useRef<HTMLDivElement>(null);
  useGSAP(
    () => {
      if (still()) return;
      gsap.from("[data-lamp]", {
        scale: 0,
        duration: 0.5,
        ease: "back.out(3)",
        stagger: 0.3,
        scrollTrigger: { trigger: root.current, start: "top 75%", once: true },
      });
    },
    { scope: root },
  );
  return <div ref={root}>{children}</div>;
}
