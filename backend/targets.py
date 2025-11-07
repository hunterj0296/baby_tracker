from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional, Tuple


ML_PER_OZ = 29.5735


@dataclass
class Range:
    low: float
    high: float


# Daily total intake anchors in oz per 24h
# Interpolate linearly between these day anchors
# Day 1: 1 oz (single-point target)
# Day 5: 12–20 oz
# Day 31: 20–22 oz
# Day 61+: 23–26 oz
DAILY_TOTAL_OZ_ANCHORS: list[tuple[int, Range]] = [
    (1, Range(1, 1)),
    (5, Range(12, 20)),
    (31, Range(20, 22)),
    (61, Range(23, 26)),
]


def _parse_day_zero() -> datetime:
    # Expected formats: YYYY-MM-DD or ISO8601 date
    day_zero_str = os.getenv("DAY_ZERO", "2025-10-28")
    try:
        d: date = date.fromisoformat(day_zero_str)
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    except Exception:
        # Fallback to today if misconfigured
        now = datetime.now(timezone.utc)
        return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)


DAY_ZERO_UTC: datetime = _parse_day_zero()


def age_days(now: Optional[datetime] = None) -> float:
    now = now or datetime.now(timezone.utc)
    return max(0.0, (now - DAY_ZERO_UTC).total_seconds() / 86400.0)


def _interp_range_oz(d: float) -> Optional[Range]:
    if d < 1:
        return None
    # If beyond last anchor, clamp to last range
    if d >= DAILY_TOTAL_OZ_ANCHORS[-1][0]:
        return DAILY_TOTAL_OZ_ANCHORS[-1][1]
    for (d0, r0), (d1, r1) in zip(DAILY_TOTAL_OZ_ANCHORS, DAILY_TOTAL_OZ_ANCHORS[1:]):
        if d0 <= d <= d1:
            t = (d - d0) / (d1 - d0) if d1 != d0 else 0.0
            return Range(
                low=r0.low + t * (r1.low - r0.low),
                high=r0.high + t * (r1.high - r0.high),
            )
    return DAILY_TOTAL_OZ_ANCHORS[-1][1]


def interp_range_oz(d: float) -> Optional[Range]:
    # Daily total range in oz
    return _interp_range_oz(d)


def interp_range_ml(d: float) -> Optional[Range]:
    # Daily total range converted to mL
    r = _interp_range_oz(d)
    if r is None:
        return None
    return Range(low=r.low * ML_PER_OZ, high=r.high * ML_PER_OZ)


def targets_for_now(now: Optional[datetime] = None) -> Tuple[Optional[Range], Optional[Range], float]:
    d = age_days(now)
    ml = interp_range_ml(d)
    oz = interp_range_oz(d)
    return ml, oz, d


def to_ml_from_oz(oz: float) -> float:
    return oz * ML_PER_OZ


def to_oz_from_ml(ml: float) -> float:
    return ml / ML_PER_OZ


