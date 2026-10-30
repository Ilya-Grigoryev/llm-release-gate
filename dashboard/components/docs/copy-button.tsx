"use client";

import { useEffect, useRef, useState } from "react";

type State = "idle" | "copied" | "manual";

const mac = () => typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

/**
 * Copies `text`. When the browser refuses (no permission, an insecure page, an old browser), it selects the code
 * instead and says which keys copy it.
 */
export function CopyButton({ text }: { text: string }) {
  const [state, setState] = useState<State>("idle");
  const button = useRef<HTMLButtonElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);

  const show = (next: State) => {
    setState(next);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setState("idle"), next === "copied" ? 2000 : 6000);
  };

  const selectCode = () => {
    const code = button.current?.closest("[data-code]")?.querySelector("pre");
    const selection = window.getSelection();
    if (!code || !selection) return;
    const range = document.createRange();
    range.selectNodeContents(code);
    selection.removeAllRanges();
    selection.addRange(range);
  };

  const copy = async () => {
    try {
      if (!navigator.clipboard) throw new Error("no clipboard");
      await navigator.clipboard.writeText(text);
      show("copied");
    } catch {
      selectCode();
      show("manual");
    }
  };

  return (
    <span className="flex items-center gap-2">
      <span aria-live="polite" className="text-sm text-ink-2">
        {state === "copied" ? "Copied" : state === "manual" ? `Selected: press ${mac() ? "⌘C" : "Ctrl+C"} to copy` : ""}
      </span>
      <button
        ref={button}
        type="button"
        onClick={copy}
        className="rounded border border-line bg-paper px-2 py-0.5 text-sm text-ink-2 hover:border-ink-3 hover:text-ink"
      >
        Copy
      </button>
    </span>
  );
}
