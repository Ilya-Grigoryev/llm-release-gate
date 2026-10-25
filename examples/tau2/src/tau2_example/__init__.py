"""tau2-bench telecom behind the gate. Importing the package prepares tau2, which reads TAU2_DATA_DIR on import and
logs every model call: the data directory defaults to the repository's data/, the log to warnings."""

import os
import sys
from pathlib import Path

from loguru import logger

DATA = Path(__file__).resolve().parents[4] / "data" / "tau2-bench" / "data"
os.environ.setdefault("TAU2_DATA_DIR", str(DATA))
logger.remove()
logger.add(sys.stderr, level="WARNING")
