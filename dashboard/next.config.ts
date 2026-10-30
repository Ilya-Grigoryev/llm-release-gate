import createMDX from "@next/mdx";
import type { NextConfig } from "next";

// Every page reads the session, so nothing here is prerendered or cached.
const nextConfig: NextConfig = {
  pageExtensions: ["ts", "tsx", "mdx"],
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

// The docs pages are MDX: text in Markdown, figures as components. GFM gives them tables.
const withMDX = createMDX({ options: { remarkPlugins: ["remark-gfm"] } });

export default withMDX(nextConfig);
