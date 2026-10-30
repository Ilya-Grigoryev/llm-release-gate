"use client";

import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { SplitText } from "gsap/SplitText";
import { useRef, type ReactNode } from "react";

gsap.registerPlugin(useGSAP, ScrollTrigger, SplitText);

const still = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

/**
 * The home page's opening, once on load: the headline's words rise in, then the parts marked `data-intro` under it.
 * globals.css hides those parts until this runs.
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
      gsap
        .timeline({ onComplete: () => split.revert() })
        .from(split.words, { yPercent: 70, opacity: 0, duration: 0.8, ease: "power3.out", stagger: 0.06 })
        .from(
          parts.filter((p) => p !== h1),
          { y: 14, opacity: 0, duration: 0.6, ease: "power2.out", stagger: 0.1 },
          "-=0.45",
        );
    },
    { scope: root },
  );
  return <div ref={root}>{children}</div>;
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
