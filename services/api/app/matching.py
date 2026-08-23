"""Thin wrapper around grp_calculator's normalization, so match keys computed
here agree with both the Streamlit calculator and db/schema.sql's
normalize_match_text()/normalize_match_day() generated columns.

This used to duplicate normalize_text/normalize_day rather than import them,
back when services/api couldn't reach grp_calculator.py at all. Now that
app/__init__.py adds the repo root to sys.path (needed anyway for real
upload parsing in app/parsing.py), importing directly is strictly better —
no drift risk. Keep this module as the one place API code asks for a match
key, rather than importing grp_calculator ad hoc everywhere.
"""

import re

from grp_calculator import normalize_day, normalize_text


_CLOCK_PATTERN = re.compile(r'^(\d{1,2}):?(\d{2})(?::?(\d{2}))?\s*(AM|PM)?$', re.IGNORECASE)
_RANGE_PATTERN = re.compile(r'^(.+?)\s*(?:-|–|to)\s*(.+?)$')


def _clock_seconds(value):
    match = _CLOCK_PATTERN.match(str(value or '').strip())
    if not match:
        return None
    hour, minute, second, meridiem = match.groups()
    hour = int(hour)
    minute = int(minute)
    second = int(second or 0)
    if minute > 59 or second > 59:
        return None
    if meridiem:
        if hour < 1 or hour > 12:
            return None
        hour = hour % 12 + (12 if meridiem.upper() == 'PM' else 0)
    elif hour > 23:
        return None
    return hour * 3600 + minute * 60 + second


def time_band_contains(time_band, point_time) -> bool:
    """Return whether a media clock time falls in a rating time range."""
    range_match = _RANGE_PATTERN.match(str(time_band or '').strip())
    point_seconds = _clock_seconds(point_time)
    if not range_match or point_seconds is None:
        return False
    start = _clock_seconds(range_match.group(1))
    end = _clock_seconds(range_match.group(2))
    if start is None or end is None:
        return False
    if end <= start:
        end += 24 * 60 * 60
    return start <= point_seconds < end or start <= point_seconds + 24 * 60 * 60 < end


def is_time_band_range(value) -> bool:
    return _RANGE_PATTERN.match(str(value or '').strip()) is not None


def make_match_key(medium, station, day, programme='', time_band='') -> str:
    combined_programme = ' '.join(
        part for part in [str(programme or '').strip(), str(time_band or '').strip()] if part
    )
    return '|'.join([
        normalize_text(medium),
        normalize_text(station),
        normalize_day(day),
        normalize_text(combined_programme),
    ])


def make_exact_match_key(medium, station, day, programme='', time_band='') -> str:
    """Build the exact key from medium, station, day, and time band.

    Programme is the fallback slot identifier for sources that do not
    provide a separate time-band value.
    """
    slot = time_band if str(time_band or '').strip() else programme
    return '|'.join([
        normalize_text(medium),
        normalize_text(station),
        normalize_day(day),
        normalize_text(slot),
    ])
