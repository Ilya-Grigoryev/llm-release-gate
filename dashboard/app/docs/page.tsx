import { redirect } from "next/navigation";
import { PAGES } from "@/lib/docs";

/** /docs opens the first page in reading order. */
export default function Docs() {
  redirect(PAGES[0].href);
}
