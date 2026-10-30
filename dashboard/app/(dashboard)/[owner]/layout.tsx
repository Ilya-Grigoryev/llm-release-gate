import { notFound } from "next/navigation";

/** `/docs/<typo>` would match a repository named after it; it is a missing docs page instead. */
export default async function Owner({ children, params }: LayoutProps<"/[owner]">) {
  if ((await params).owner === "docs") notFound();
  return children;
}
