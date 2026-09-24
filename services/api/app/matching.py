"""Shared matching-key helpers for the API.

The API delegates normalization to grp_calculator.py so Streamlit uploads,
FastAPI uploads, match reports, and calculation tests all agree on station,
day, and time-band behavior.
"""

from grp_calculator import (
    is_time_band_range,
    normalize_day,
    normalize_medium_type,
    normalize_station_for_match,
    normalize_text,
    time_band_contains,
)


def normalize_station(value) -> str:
    """Normalize a station/channel name for exact-match comparison."""
    return normalize_station_for_match(value)


def normalize_medium(value) -> str:
    """Normalize a medium for match-key comparison.

    Canonicalizes to the same TV / CABLE TV / RADIO / OTHER / MISSING
    buckets grp_calculator.normalize_medium_type() already uses for GRP
    bucketing, rather than a plain uppercase/whitespace normalize_text().
    Real vendor files spell the same medium differently between a ratings
    export and a spend export ("TV" vs "Terrestrial TV" vs "Terrestrial
    Tv") — those disagree under normalize_text() alone, which silently
    fails every match key built from them (medium is one of the key's
    components), station/day/time-band agreement notwithstanding. A real
    upload pair hit exactly this: 0 of 950 spots matched before this
    normalization, 946 after.
    """
    return normalize_medium_type(value)


def make_match_key(medium, station, day, programme='', time_band='') -> str:
    combined_programme = ' '.join(
        part for part in [str(programme or '').strip(), str(time_band or '').strip()] if part
    )
    return '|'.join([
        normalize_medium(medium),
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
        normalize_medium(medium),
        normalize_station(station),
        normalize_day(day),
        normalize_text(slot),
    ])
