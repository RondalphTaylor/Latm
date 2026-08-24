from __future__ import annotations

import asyncio
import csv
import hashlib
import io
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.domain.mlb_statcast import MlbStatcastPitchObservation, MlbStatcastPlayerRole
from app.providers.sports.base import (
    SportsProviderResponseError,
    SportsProviderUnavailableError,
)

_REQUIRED_CSV_COLUMNS = frozenset(
    {
        "game_date",
        "release_speed",
        "player_name",
        "batter",
        "pitcher",
        "events",
        "description",
        "game_type",
        "type",
        "launch_speed",
        "launch_angle",
        "release_spin_rate",
        "game_pk",
        "estimated_woba_using_speedangle",
        "woba_value",
        "woba_denom",
        "launch_speed_angle",
        "at_bat_number",
        "pitch_number",
    }
)
_SUPPORTED_GAME_TYPES = frozenset({"R", "F", "D", "L", "W"})


class BaseballSavantCsvRow(BaseModel):
    """Validated official CSV fields used by the quantitative contract."""

    model_config = ConfigDict(extra="ignore")

    game_date: date
    release_speed: Decimal | None = Field(default=None, ge=0, le=120)
    player_name: str = Field(min_length=1, max_length=200)
    batter: int = Field(gt=0)
    pitcher: int = Field(gt=0)
    events: str | None = Field(default=None, max_length=100)
    description: str = Field(min_length=1, max_length=100)
    game_type: str = Field(min_length=1, max_length=1)
    type: str = Field(min_length=1, max_length=10)
    launch_speed: Decimal | None = Field(default=None, ge=0, le=130)
    launch_angle: Decimal | None = Field(default=None, ge=-90, le=90)
    release_spin_rate: Decimal | None = Field(default=None, ge=0, le=5000)
    game_pk: int = Field(gt=0)
    estimated_woba_using_speedangle: Decimal | None = Field(default=None, ge=0, le=5)
    woba_value: Decimal | None = Field(default=None, ge=0, le=5)
    woba_denom: Decimal | None = Field(default=None, ge=0, le=1)
    launch_speed_angle: int | None = Field(default=None, ge=1, le=6)
    at_bat_number: int = Field(ge=1)
    pitch_number: int = Field(ge=1)

    @model_validator(mode="before")
    @classmethod
    def blank_csv_values_are_missing(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        return {key: None if item == "" else item for key, item in value.items()}


@dataclass(frozen=True)
class BaseballSavantQueryBatch:
    """One bounded official CSV response and its validated observations."""

    role: MlbStatcastPlayerRole
    requested_player_ids: tuple[str, ...]
    window_start_date: date
    window_end_date: date
    rows: tuple[MlbStatcastPitchObservation, ...]
    retrieved_at: datetime
    response_sha256: str


class BaseballSavantStatcastProvider:
    """Read-only adapter for official Baseball Savant Statcast Search CSV data."""

    name = "baseball_savant"

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float,
        max_retries: int,
        request_interval_seconds: float,
        max_response_bytes: int,
        max_rows: int,
        retry_backoff_seconds: float = 1.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds)
        self._max_retries = max_retries
        self._request_interval_seconds = request_interval_seconds
        self._max_response_bytes = max_response_bytes
        self._max_rows = max_rows
        self._retry_backoff_seconds = retry_backoff_seconds
        self._transport = transport
        self._last_request_started: float | None = None
        self._pacing_lock = asyncio.Lock()

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            transport=self._transport,
            follow_redirects=False,
        )

    async def _pace_request(self) -> None:
        async with self._pacing_lock:
            if self._last_request_started is not None:
                loop = asyncio.get_running_loop()
                remaining = self._request_interval_seconds - (
                    loop.time() - self._last_request_started
                )
                if remaining > 0:
                    await asyncio.sleep(remaining)
            self._last_request_started = asyncio.get_running_loop().time()

    async def _get_csv(
        self,
        client: httpx.AsyncClient,
        *,
        params: list[tuple[str, str | int | float | bool | None]],
    ) -> bytes:
        path = "/statcast_search/csv"
        for attempt in range(self._max_retries + 1):
            try:
                await self._pace_request()
                response = await client.get(path, params=params)
                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                if response.is_error:
                    raise SportsProviderResponseError(
                        f"Baseball Savant returned HTTP {response.status_code}"
                    )
                content_length = response.headers.get("Content-Length")
                if content_length is not None and int(content_length) > self._max_response_bytes:
                    raise SportsProviderResponseError(
                        "Baseball Savant response exceeded the configured byte limit"
                    )
                if len(response.content) > self._max_response_bytes:
                    raise SportsProviderResponseError(
                        "Baseball Savant response exceeded the configured byte limit"
                    )
                return response.content
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                if attempt >= self._max_retries:
                    raise SportsProviderUnavailableError(
                        "Baseball Savant remained unavailable after bounded retries"
                    ) from exc
                retry_delay = self._retry_backoff_seconds * (2**attempt)
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
                    retry_after = exc.response.headers.get("Retry-After")
                    if retry_after is not None:
                        with suppress(ValueError):
                            retry_delay = max(retry_delay, min(float(retry_after), 60.0))
                await asyncio.sleep(retry_delay)
            except ValueError as exc:
                raise SportsProviderResponseError(
                    "Baseball Savant returned an invalid Content-Length"
                ) from exc
        raise AssertionError("Baseball Savant retry loop exited unexpectedly")

    @staticmethod
    def _observation(
        row: BaseballSavantCsvRow,
        *,
        role: MlbStatcastPlayerRole,
    ) -> MlbStatcastPitchObservation:
        return MlbStatcastPitchObservation(
            query_role=role,
            game_pk=row.game_pk,
            game_date=row.game_date,
            game_type=row.game_type,
            batter_id=str(row.batter),
            pitcher_id=str(row.pitcher),
            at_bat_number=row.at_bat_number,
            pitch_number=row.pitch_number,
            event=row.events,
            description=row.description,
            result_type=row.type,
            release_speed_mph=row.release_speed,
            release_spin_rate_rpm=row.release_spin_rate,
            launch_speed_mph=row.launch_speed,
            launch_angle_degrees=row.launch_angle,
            launch_speed_angle=row.launch_speed_angle,
            estimated_woba_on_contact=row.estimated_woba_using_speedangle,
            woba_value=row.woba_value,
            woba_denom=row.woba_denom,
        )

    def _parse_csv(
        self,
        content: bytes,
        *,
        role: MlbStatcastPlayerRole,
        requested_player_ids: tuple[str, ...],
        window_start_date: date,
        window_end_date: date,
    ) -> tuple[MlbStatcastPitchObservation, ...]:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise SportsProviderResponseError("Baseball Savant CSV was not valid UTF-8") from exc
        reader = csv.DictReader(io.StringIO(text))
        fieldnames = set(reader.fieldnames or ())
        if not fieldnames >= _REQUIRED_CSV_COLUMNS:
            missing = sorted(_REQUIRED_CSV_COLUMNS - fieldnames)
            raise SportsProviderResponseError(
                f"Baseball Savant CSV was missing required columns: {', '.join(missing)}"
            )
        observations: list[MlbStatcastPitchObservation] = []
        requested = set(requested_player_ids)
        try:
            for raw_row in reader:
                if len(observations) >= self._max_rows:
                    raise SportsProviderResponseError(
                        "Baseball Savant response exceeded the configured row limit"
                    )
                row = BaseballSavantCsvRow.model_validate(raw_row)
                if not window_start_date <= row.game_date <= window_end_date:
                    raise SportsProviderResponseError(
                        "Baseball Savant returned a row outside the requested date window"
                    )
                if row.game_type not in _SUPPORTED_GAME_TYPES:
                    raise SportsProviderResponseError(
                        "Baseball Savant returned a non-regular/postseason game row"
                    )
                selected_id = str(
                    row.pitcher if role is MlbStatcastPlayerRole.PITCHER else row.batter
                )
                if selected_id not in requested:
                    raise SportsProviderResponseError(
                        "Baseball Savant returned an unrequested player row"
                    )
                observations.append(self._observation(row, role=role))
        except ValidationError as exc:
            raise SportsProviderResponseError("Baseball Savant CSV row failed validation") from exc
        return tuple(observations)

    async def get_player_rows(
        self,
        *,
        role: MlbStatcastPlayerRole,
        player_ids: tuple[str, ...],
        window_start_date: date,
        window_end_date: date,
    ) -> BaseballSavantQueryBatch:
        """Retrieve a bounded multi-player rolling window from the official CSV surface."""
        if window_start_date > window_end_date:
            raise ValueError("Statcast window_start_date must not be after window_end_date")
        if any(not player_id.isdigit() for player_id in player_ids):
            raise ValueError("Statcast player IDs must be official numeric MLB identities")
        normalized_ids = tuple(sorted(set(player_ids), key=int))
        if len(normalized_ids) != len(player_ids) or not normalized_ids:
            raise ValueError("Statcast player IDs must be nonempty and unique")
        lookup_name = (
            "pitchers_lookup[]" if role is MlbStatcastPlayerRole.PITCHER else "batters_lookup[]"
        )
        params: list[tuple[str, str | int | float | bool | None]] = [
            ("all", "true"),
            ("type", "details"),
            ("player_type", role.value),
            ("game_date_gt", window_start_date.isoformat()),
            ("game_date_lt", window_end_date.isoformat()),
            ("hfGT", "R|PO|"),
            *((lookup_name, player_id) for player_id in normalized_ids),
        ]
        async with self._client() as client:
            content = await self._get_csv(client, params=params)
        retrieved_at = datetime.now(UTC)
        rows = self._parse_csv(
            content,
            role=role,
            requested_player_ids=normalized_ids,
            window_start_date=window_start_date,
            window_end_date=window_end_date,
        )
        return BaseballSavantQueryBatch(
            role=role,
            requested_player_ids=normalized_ids,
            window_start_date=window_start_date,
            window_end_date=window_end_date,
            rows=rows,
            retrieved_at=retrieved_at,
            response_sha256=hashlib.sha256(content).hexdigest(),
        )
