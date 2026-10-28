"""Application resource container for the supported single-data-root process."""
from dataclasses import dataclass
from pathlib import Path
from typing import Any

@dataclass(frozen=True)
class AppContext:
    data_root: Path
    settings: dict
    repository: Any
    event_bus: Any
    worker: Any
