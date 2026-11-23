"""The synthetic 168-hour site history page 06 shows when nothing is uploaded.

The page used to build this inside its own body from ``datetime.now(timezone.utc)``.
The PV and wind series carry a ripple keyed to the **row index** (``sin(i * 0.17)``
and ``sin(i * 0.21 + 0.7)``), while load and tariff are keyed to the hour of day.
Moving the anchor by one hour therefore moves the 24-hour target window across
that ripple: the daily load total stays 510 kWh, the projected annual energy cost
does not. ``tests`` and the work log both found this the hard way — 7,709.55 at
14:00 UTC vs 5,332.57 at 02:00 UTC on the same code.

This module keeps the numbers verbatim and makes the anchor an argument instead of
an inheritance from the wall clock. It does not decide what the anchor should be:
the page passes the demo-clock hour (current UTC hour by default), and a reader
who wants a recorded number back pins that hour. Nothing here writes to a device,
and nothing here is a site measurement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import math

#: The page's historical window: seven days of hourly rows ending at the anchor.
SYNTHETIC_HISTORY_HOURS = 168


def demo_anchor_for_hour(
    now_utc: datetime,
    demo_hour: int,
    *,
    demo_date: date | None = None,
) -> datetime:
    """Return ``demo_date`` (today by default) at ``demo_hour`` UTC, truncated to the hour.

    The demo clock is a dial, not a clock: a selected date and hour are applied
    literally, even when that instant has not happened yet. Passing the defaults
    (``now_utc.date()`` and ``now_utc.hour``) therefore reproduces the unpinned
    window exactly, because the pages already truncate ``now`` to the hour.

    Page 05's synthetic load carries a weekday term, so its 24-hour cost depends on
    the date as well as the hour; page 06 has no weekday term and only needs the hour.
    The date argument exists so 05 can pin both and still default to live.
    """
    if not isinstance(now_utc, datetime):
        raise ValueError("now_utc must be a datetime")
    if now_utc.tzinfo is None or now_utc.utcoffset() is None:
        raise ValueError("now_utc must be timezone-aware")
    if isinstance(demo_hour, bool) or not isinstance(demo_hour, int):
        raise ValueError("demo_hour must be an integer from 0 to 23")
    if not 0 <= demo_hour <= 23:
        raise ValueError("demo_hour must be an integer from 0 to 23")
    if demo_date is None:
        demo_date = now_utc.astimezone(timezone.utc).date()
    if isinstance(demo_date, datetime) or not isinstance(demo_date, date):
        raise ValueError("demo_date must be a date, not a datetime")
    return datetime(
        demo_date.year, demo_date.month, demo_date.day, demo_hour, tzinfo=timezone.utc
    )


@dataclass(frozen=True)
class SyntheticSiteHistory:
    """The synthetic window plus the four signals the page feeds to the forecast."""

    anchor_utc: datetime
    timestamps: tuple[datetime, ...]
    pv_power_kw: tuple[float, ...]
    wind_power_kw: tuple[float, ...]
    load_kw: tuple[float, ...]
    tariff_per_kwh: tuple[float, ...]


def build_synthetic_site_history(
    anchor_utc: datetime,
    *,
    pv_rated_kw: float,
    wind_rated_kw: float,
) -> SyntheticSiteHistory:
    """Build the page's default window ending at ``anchor_utc``, truncated to the hour.

    ``anchor_utc`` must be timezone-aware; a naive timestamp would silently mean the
    host's local time and make the window depend on the machine again. The returned
    rows are independent of the host clock.
    """
    if not isinstance(anchor_utc, datetime):
        raise ValueError("anchor_utc must be a datetime")
    if anchor_utc.tzinfo is None or anchor_utc.utcoffset() is None:
        raise ValueError("anchor_utc must be timezone-aware")
    for name, value in (("pv_rated_kw", pv_rated_kw), ("wind_rated_kw", wind_rated_kw)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be a finite number")
        if not math.isfinite(float(value)) or float(value) < 0:
            raise ValueError(f"{name} must be a non-negative finite number")

    anchor = anchor_utc.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    timestamps = tuple(anchor - timedelta(hours=SYNTHETIC_HISTORY_HOURS - 1 - i)
                       for i in range(SYNTHETIC_HISTORY_HOURS))
    pv_capacity = float(pv_rated_kw)
    wind_capacity = float(wind_rated_kw)

    pv: list[float] = []
    wind: list[float] = []
    load: list[float] = []
    tariff: list[float] = []
    for i, stamp in enumerate(timestamps):
        hour = stamp.hour
        solar = max(0.0, 30.0 * math.sin(math.pi * (hour - 6) / 12.0))
        pv.append(min(pv_capacity, solar * (0.86 + 0.08 * math.sin(i * 0.17))))
        wind.append(min(wind_capacity, 8.0 + 3.0 * math.sin(i * 0.21 + 0.7)))
        load.append(20.0 + 4.0 * (hour in range(17, 23)) + 2.0 * (hour in range(7, 10)))
        tariff.append(0.08 if hour < 6 else 0.27 if hour in range(17, 22) else 0.16)

    return SyntheticSiteHistory(
        anchor_utc=anchor,
        timestamps=timestamps,
        pv_power_kw=tuple(pv),
        wind_power_kw=tuple(wind),
        load_kw=tuple(load),
        tariff_per_kwh=tuple(tariff),
    )
