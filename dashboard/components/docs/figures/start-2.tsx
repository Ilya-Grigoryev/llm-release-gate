import { CommentCard, FigureHead } from "./kit";

/** The gate's comment on the first pull request, as the action posts it. */
const COMMENT = `
\`invoice\` · **Release gate: 🆕 no base version**

The target branch has no version of this pipeline yet, so there is nothing to compare with.
The candidate scores 1.000 on 1 cases (first run of each) · config a7fbf796 · set a5ccf81e

[Job log](https://github.com/OWNER/REPO/actions/runs/RUN_ID)
`;

/** The first comment. */
export default function Start2({}: { alt: string }) {
  return (
    <>
      <FigureHead tag="Example output, the model replaced by a fixed answer" />
      <CommentCard markdown={COMMENT} />
    </>
  );
}
