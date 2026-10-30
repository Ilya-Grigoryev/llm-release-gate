import type { ComponentType } from "react";
import { Figure } from "../figure";
import Connect1 from "./connect-1";
import Connect2 from "./connect-2";
import Dashboard1 from "./dashboard-1";
import Dashboard2 from "./dashboard-2";
import Home1 from "./home-1";
import HowItDecides1 from "./how-it-decides-1";
import HowItDecides2 from "./how-it-decides-2";
import HowItDecides3 from "./how-it-decides-3";
import HowItDecides4 from "./how-it-decides-4";
import HowItWorks1 from "./how-it-works-1";
import HowItWorks2 from "./how-it-works-2";
import Limits1 from "./limits-1";
import Limits2 from "./limits-2";
import Method1 from "./method-1";
import Method2 from "./method-2";
import Method3 from "./method-3";
import ReadAVerdict1 from "./read-a-verdict-1";
import ReadAVerdict2 from "./read-a-verdict-2";
import Start1 from "./start-1";
import Start2 from "./start-2";
import WhatItCatches1 from "./what-it-catches-1";
import WhatItCatches2 from "./what-it-catches-2";
import WriteTests1 from "./write-tests-1";
import WriteTests2 from "./write-tests-2";

/** Every figure of the docs by its id (`<page>-<n>`, in the order the page shows them). */
const FIGURES: Record<string, { Component: ComponentType<{ alt: string }>; wide?: boolean; framed?: boolean }> = {
  "connect-1": { Component: Connect1, wide: true },
  "connect-2": { Component: Connect2, wide: true },
  "dashboard-1": { Component: Dashboard1, wide: true },
  "dashboard-2": { Component: Dashboard2, wide: true },
  "home-1": { Component: Home1, wide: true, framed: false },
  "how-it-decides-1": { Component: HowItDecides1 },
  "how-it-decides-2": { Component: HowItDecides2 },
  "how-it-decides-3": { Component: HowItDecides3, wide: true },
  "how-it-decides-4": { Component: HowItDecides4, wide: true },
  "how-it-works-1": { Component: HowItWorks1, wide: true },
  "how-it-works-2": { Component: HowItWorks2 },
  "limits-1": { Component: Limits1 },
  "limits-2": { Component: Limits2, wide: true },
  "method-1": { Component: Method1 },
  "method-2": { Component: Method2 },
  "method-3": { Component: Method3, wide: true },
  "read-a-verdict-1": { Component: ReadAVerdict1 },
  "read-a-verdict-2": { Component: ReadAVerdict2, wide: true },
  "start-1": { Component: Start1 },
  "start-2": { Component: Start2 },
  "what-it-catches-1": { Component: WhatItCatches1, wide: true },
  "what-it-catches-2": { Component: WhatItCatches2, wide: true },
  "write-tests-1": { Component: WriteTests1, wide: true },
  "write-tests-2": { Component: WriteTests2 },
};

/** A caption's `code` spans, written in backticks as in the page's text. */
function inline(text: string) {
  return text.split(/`([^`]+)`/).map((piece, i) => (i % 2 ? <code key={i}>{piece}</code> : piece));
}

/** A figure of the docs: its drawing, the one sentence that says what to see in it, and a text alternative. */
export function Fig({ id, caption, alt }: { id: string; caption: string; alt: string }) {
  const figure = FIGURES[id];
  if (!figure) throw new Error(`no figure ${id}`);
  const { Component, wide, framed } = figure;
  return (
    <Figure caption={inline(caption)} alt={alt.replaceAll("`", "")} wide={wide} framed={framed}>
      <Component alt={alt} />
    </Figure>
  );
}
