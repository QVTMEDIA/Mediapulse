"""Shared matching-key helpers for the API.

The API delegates normalization to grp_calculator.py so Streamlit uploads,
FastAPI uploads, match reports, and calculation tests all agree on station,
day, and time-band behavior.
"""

from grp_calculator import (
    is_time_band_range,
    normalize_day,
    normalize_station_for_match,
    normalize_text,
    time_band_contains,
)


def normalize_station(value) -> str:
    """Normalize a station/channel name for exact-match comparison."""
    return normalize_station_for_match(value)


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
        normalize_station(station),
        normalize_day(day),
        normalize_text(slot),
    ])
