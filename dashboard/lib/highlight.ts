import { createCssVariablesTheme, createHighlighterCore, type ThemedToken } from "shiki/core";
import { createJavaScriptRegexEngine } from "shiki/engine/javascript";

/** Token colours are the site's `--code-*` variables (globals.css), so they follow light and dark. */
const theme = createCssVariablesTheme({ name: "site", variablePrefix: "--code-", fontStyle: false });

/** The languages the docs use; one highlighter per server, created on first use. */
const highlighter = createHighlighterCore({
  themes: [theme],
  langs: [
    import("shiki/langs/go.mjs"),
    import("shiki/langs/javascript.mjs"),
    import("shiki/langs/json.mjs"),
    import("shiki/langs/python.mjs"),
    import("shiki/langs/shellscript.mjs"),
    import("shiki/langs/toml.mjs"),
    import("shiki/langs/yaml.mjs"),
  ],
  engine: createJavaScriptRegexEngine(),
});

const SHELL = new Set(["sh", "bash", "shell", "shellscript", "zsh"]);
const STRING = "var(--code-token-string)";

/**
 * `code` as lines of coloured tokens, or null for a language it does not know (plain text, say). The shell grammar
 * calls every argument a string; only quoted ones keep that colour, so a command line reads as text.
 */
export async function highlight(code: string, language: string): Promise<ThemedToken[][] | null> {
  const h = await highlighter;
  if (!h.getLoadedLanguages().includes(language)) return null;
  const lines = h.codeToTokens(code, { lang: language, theme: "site" }).tokens;
  if (!SHELL.has(language)) return lines;
  return lines.map((line) => line.map((t) => (t.color === STRING && !/^["']/.test(t.content) ? { ...t, color: undefined } : t)));
}
