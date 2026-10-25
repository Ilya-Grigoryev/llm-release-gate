"""Gate a pull or merge request from the root of its repository: `pr.sh` runs both versions and the gate."""

import os
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name("pr.sh")


def main(argv: list[str] | None = None) -> None:
    os.execvp("bash", ["bash", str(SCRIPT), *(sys.argv[1:] if argv is None else argv)])


if __name__ == "__main__":
    main()
