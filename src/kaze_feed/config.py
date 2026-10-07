from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    poll_interval_seconds: int = 300
    recent_hours: int = 36
    retention_days: int = 30
    timeout_seconds: float = 8.0
    concurrency: int = 4
    max_response_bytes: int = 2 * 1024 * 1024
    max_items_per_feed: int = 200

    @classmethod
    def from_env(cls) -> "Settings":
        root = os.environ.get("KAZE_FEED_DATA_DIR")
        return cls(data_dir=Path(root).expanduser().resolve() if root else Path.home() / ".kaze-feed")

    @property
    def database(self) -> Path:
        return self.data_dir / "feed.sqlite3"
