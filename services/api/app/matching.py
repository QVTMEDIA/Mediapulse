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

from grp_calculator import normalize_day, normalize_text


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
