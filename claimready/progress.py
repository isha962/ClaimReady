from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import TextIO

from .models import RequestEvent


@dataclass(slots=True)
class ProgressReporter:
    stream: TextIO = sys.stdout

    def write(self, message: str) -> None:
        print(message, file=self.stream)

    def facility_start(self, facility_id: int) -> None:
        self.write(f"Facility {facility_id}: starting sync")

    def endpoint_start(self, facility_id: int, endpoint: str) -> None:
        self.write(f"Facility {facility_id}: syncing {endpoint}")

    def endpoint_success(self, facility_id: int, endpoint: str, record_count: int) -> None:
        self.write(f"Facility {facility_id}: {endpoint} success ({record_count} records)")

    def facility_complete(self, facility_id: int) -> None:
        self.write(f"Facility {facility_id}: complete")

    def facility_failed(self, facility_id: int) -> None:
        self.write(f"Facility {facility_id}: failed")

    def api_check_result(self, url: str, classification: str, status_code: int | None) -> None:
        status_text = f"HTTP {status_code}" if status_code is not None else "no status"
        self.write(f"CHECK {url} -> {classification} ({status_text})")

    def final_failure(self, failure: Exception) -> None:
        self.write(f"Final failure: {failure}")

    def __call__(self, event: RequestEvent) -> None:
        if event.outcome == "retry":
            status_text = f"HTTP {event.status_code}" if event.status_code is not None else "network failure"
            wait_text = f"{event.wait_seconds:.1f}s" if event.wait_seconds is not None else "unknown"
            self.write(
                f"Retry {event.attempt} for {event.url}: {status_text}; waiting {wait_text}"
            )
        elif event.outcome == "failure":
            status_text = f"HTTP {event.status_code}" if event.status_code is not None else "network failure"
            self.write(f"Final failure for {event.url}: {status_text}")
