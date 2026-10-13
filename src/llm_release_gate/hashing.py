"""Content hashes that identify configs and test sets."""

import hashlib
import json
from pathlib import Path
from typing import Any


def canonical_hash(obj: Any) -> str:
    """sha256 of canonical JSON: sorted keys, no whitespace, UTF-8."""
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
