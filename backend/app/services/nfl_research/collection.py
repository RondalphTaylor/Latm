"""Manually resumable, bounded NFL history ingestion through the paper localhost API."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from datetime import date, timedelta

import httpx

_BASE_URL = "http://localhost:8000"
_MIN_DATE = date(2018, 8, 1)
_MAX_DATE = date(2026, 2, 28)
_STATUSES = ("scheduled", "in_progress", "final", "postponed", "canceled", "unknown")
_COUNTS = ("fetched", "teams_persisted", "events_persisted", *_STATUSES)


def _valid_ingestion(payload: object, start: date, end: date) -> bool:
    if not isinstance(payload, dict):
        return False
    if (
        payload.get("provider") != "balldontlie_nfl"
        or payload.get("start_date") != start.isoformat()
        or payload.get("end_date") != end.isoformat()
    ):
        return False
    if any(type(payload.get(key)) is not int or payload[key] < 0 for key in _COUNTS):
        return False
    return bool(
        sum(payload[key] for key in _STATUSES) == payload["fetched"]
        and payload["events_persisted"] == payload["fetched"]
    )


def collect_history(
    client: httpx.Client,
    *,
    start_date: date,
    end_date: date,
    max_windows: int = 1,
    emit: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    """Collect inclusive windows; return a manual resume date, not a durable checkpoint.

    Failures can occur after the server persisted a window. Retrying that same date
    relies on the existing idempotent ingestion; this runner never rolls data back.
    """
    if not _MIN_DATE <= start_date <= end_date <= _MAX_DATE:
        raise ValueError("dates must be ordered within 2018-08-01 through 2026-02-28")
    if type(max_windows) is not int or not 1 <= max_windows <= 48:
        raise ValueError("max_windows must be between 1 and 48")
    current = start_date
    windows = 0
    failure: str | None = None
    http_status: int | None = None
    while current <= end_date and windows < max_windows:
        window_end = min(current + timedelta(days=30), end_date)
        stage = "health"
        try:
            health_response = client.get(f"{_BASE_URL}/health", follow_redirects=False)
            health_response.raise_for_status()
            health = health_response.json()
            if (
                not isinstance(health, dict)
                or health.get("status") != "ok"
                or health.get("trading_mode") != "paper"
            ):
                failure = "paper_health_gate_failed"
                break
            stage = "ingestion"
            response = client.post(
                f"{_BASE_URL}/events/ingest",
                params={
                    "provider": "balldontlie_nfl",
                    "start_date": current.isoformat(),
                    "end_date": window_end.isoformat(),
                },
                follow_redirects=False,
            )
            response.raise_for_status()
            payload = response.json()
            if not _valid_ingestion(payload, current, window_end):
                failure = "malformed_ingestion_response"
                break
        except httpx.HTTPStatusError as exc:
            failure = f"{stage}_http_error"
            http_status = exc.response.status_code
            break
        except httpx.RequestError:
            failure = f"{stage}_request_error"
            break
        except ValueError:
            failure = f"malformed_{stage}_response"
            break
        # Only validated, explicitly allowlisted fields reach output.
        record: dict[str, object] = {
            "type": "window",
            "start_date": current.isoformat(),
            "end_date": window_end.isoformat(),
        }
        record.update({key: payload[key] for key in _COUNTS})
        if emit is not None:
            emit(record)
        windows += 1
        current = window_end + timedelta(days=1)
    summary: dict[str, object] = {
        "type": "summary",
        "windows_completed": windows,
        "completed": current > end_date,
        "next_start": current.isoformat() if current <= end_date else None,
        "end_date": end_date.isoformat(),
        "failure": failure,
        "http_status": http_status,
    }
    if emit is not None:
        emit(summary)
    return summary


def _print_json(record: dict[str, object]) -> None:
    print(json.dumps(record, sort_keys=True), flush=True)


def main() -> int:
    """Run bounded manual collection without reading credentials or writing files."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", required=True, type=date.fromisoformat)
    parser.add_argument("--end-date", required=True, type=date.fromisoformat)
    parser.add_argument("--max-windows", type=int, default=1)
    args = parser.parse_args()
    try:
        with httpx.Client(timeout=600, trust_env=False) as client:
            result = collect_history(
                client,
                start_date=args.start_date,
                end_date=args.end_date,
                max_windows=args.max_windows,
                emit=_print_json,
            )
    except ValueError as exc:
        parser.error(str(exc))
    return 1 if result["failure"] is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
