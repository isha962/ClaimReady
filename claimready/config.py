from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Settings:
    base_url: str = "https://hackathon.prod.pulsefoundry.ai"
    database_path: str = "claimready.sqlite3"
    max_concurrency: int = 5
    max_retries: int = 5
    timeout_seconds: float = 15.0
