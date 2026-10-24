"""Build the SROIE golden set: random receipts from a split, both inputs copied next to the cases.

An existing manifest is the source of truth: the set is rebuilt from its ids, not resampled.
"""

import argparse
import random
import re
import shutil
from pathlib import Path

import yaml

from llm_release_gate.golden import validate
from llm_release_gate.hashing import file_hash
from sroie_example.pipeline import SCORING, cases


def store(company: str) -> str:
    """Store chain from the company field: branch in parentheses, legal form and punctuation dropped."""
    name = re.sub(r"\(.*?\)", " ", company.upper())
    name = re.sub(r"\b(SDN|BHD|S/B|PLC|LTD)\b\.?", " ", name)
    return " ".join(re.sub(r"[^A-Z0-9& ]", "", name).split())


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--src", type=Path, default=Path("../../data/SROIE2019/train"))
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("-n", type=int, default=30, help="number of cases")
    p.add_argument("--skip", type=int, default=10, help="leave out the first receipts")
    p.add_argument("--out", type=Path, default=Path("../../data/golden/sroie"))
    p.add_argument("--manifest", type=Path, default=Path("golden/sroie.yaml"))
    p.add_argument(
        "--rehash",
        action="store_true",
        help="same receipts, new set hash: record it in the manifest (after a change to SCORING)",
    )
    args = p.parse_args()
    if args.out.exists() and any(args.out.iterdir()):
        raise SystemExit(f"{args.out} is not empty; delete it first")

    pool = cases(args.src)[args.skip :]
    manifest = (
        yaml.safe_load(args.manifest.read_text()) if args.manifest.exists() else None
    )
    if manifest:
        ids = set(manifest["ids"])
        picked = [c for c in pool if c.id in ids]
        if len(picked) != len(ids):
            raise SystemExit(f"{args.src} lacks receipts listed in {args.manifest}")
    else:
        picked = random.Random(args.seed).sample(pool, args.n)
    picked.sort(key=lambda c: c.id)
    (args.out / "inputs").mkdir(parents=True)
    for case in picked:
        refs = {}
        for name, src in case.inputs.items():
            ref = f"inputs/{case.id}{src.suffix}"
            shutil.copyfile(src, args.out / ref)
            if file_hash(args.out / ref) != file_hash(src):
                raise SystemExit(f"copy of {src} differs from the source")
            refs[name] = ref
        chain = store(case.expected["company"])
        doc = {
            "id": case.id,
            "version": 1,
            "slices": {"store": chain},
            "source": f"SROIE2019/{args.src.name}/{case.id}",
            "input": refs,
            "expected": case.expected,
            "scoring": SCORING,
        }
        (args.out / f"{case.id}.yaml").write_text(
            yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
        )
        print(f"{case.id}  {chain:30}  {case.expected['company']}")

    set_hash, errors = validate(args.out)
    if errors:
        raise SystemExit("\n".join(errors))
    if manifest:
        if set_hash != manifest["sha256"] and not args.rehash:
            raise SystemExit(
                f"rebuilt set hash {set_hash} differs from {args.manifest}; --rehash records it"
            )
        if set_hash != manifest["sha256"]:
            manifest["sha256"] = set_hash
            args.manifest.write_text(yaml.safe_dump(manifest, sort_keys=False))
        print(f"{len(picked)} cases rebuilt from {args.manifest}, sha256 {set_hash}")
        return
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        yaml.safe_dump(
            {
                "source": f"SROIE2019/{args.src.name}",
                "seed": args.seed,
                "n": args.n,
                "skip_first": args.skip,
                "sha256": set_hash,
                "ids": [c.id for c in picked],
            },
            sort_keys=False,
        )
    )
    print(f"{len(picked)} cases in {args.out}, sha256 {set_hash}")


if __name__ == "__main__":
    main()
