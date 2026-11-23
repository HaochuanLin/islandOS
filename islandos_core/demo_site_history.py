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
the page still passes "now" by default, and a caller that wants a repeatable
demonstration can pass a fixed hour. Nothing here writes to a device, and nothing
here is a site measurement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math

#: The page's historical window: seven days of hourly rows ending at the anchor.
SYNTHETIC_HISTORY_HOURS = 168


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
