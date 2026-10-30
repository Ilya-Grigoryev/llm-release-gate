import { Children, isValidElement, type ReactElement, type ReactNode } from "react";
import { Tabs } from "./tabs";

type TabProps = { label: string; children?: ReactNode };

/** One language of `LanguageTabs`. */
export function Tab({ children }: TabProps) {
  return <>{children}</>;
}

/** The same code in several languages, written in MDX as `<LanguageTabs><Tab label="Python">…</Tab>…</LanguageTabs>`. */
export function LanguageTabs({ children }: { children?: ReactNode }) {
  const tabs = Children.toArray(children).filter((c): c is ReactElement<TabProps> => isValidElement(c));
  return <Tabs label="Language" items={tabs.map((t) => ({ label: t.props.label, content: t.props.children }))} />;
}
