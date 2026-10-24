"""Computes rating_matches for media_activity rows against a project's
attached ratings.

Exact matching is a plain dict lookup on the normalized match key (see
app/matching.py) — no need for grp_calculator's DataFrame-merge machinery
just to pick a single rating row per key. Fuzzy suggestions reuse
grp_calculator.build_unmatched_suggestions() directly rather than
reimplementing its candidate-tiering (same medium+channel+day, then
same medium+channel, then same medium+day) and text-similarity scoring.
"""

import logging
from dataclasses import dataclass
from datetime import timezone
from typing import Dict, List, Optional

import grp_calculator as calc
import pandas as pd

from .matching import (
    is_time_band_range,
    make_exact_match_key,
    make_match_key,
    normalize_day,
    normalize_medium,
    normalize_station,
    time_band_contains,
)

logger = logging.getLogger(__name__)


@dataclass
class ComputedMatch:
    media_activity_id: str
    match_status: str  # 'exact' | 'suggested' | 'unmatched'
    matched_rating_id: Optional[str]
    match_confidence: Optional[float]
    match_key: str


STATION_SUGGESTION_THRESHOLD = 0.78

# grp_calculator.build_unmatched_suggestions costs roughly O(rows x
# candidates-per-group) -- each row still needing a fuzzy match runs a
# rapidfuzz text-similarity scan against every candidate rating sharing its
# medium/channel/day (or medium/day) group. On a large upload where many
# rows genuinely miss an exact match, that scan can pin the single CPU core
# this app typically runs on (Render's free/starter tiers) for minutes.
# Because Python threads share one GIL, running it inside match_jobs.py's
# background executor doesn't add capacity -- it only keeps the HTTP request
# itself from timing out while everything else sharing that process (other
# users' requests, platform health checks) stalls behind it, which is what
# actually presents as "the app crashed" at scale.
#
# Past this many rows still needing a fuzzy scan (after the cheap
# station-coverage prefilter below already dropped the hopeless ones), skip
# the fuzzy tier entirely and leave them 'unmatched' rather than risk that --
# exact matching (the dict lookup above) is completely unaffected and stays
# instant at any row count. A capped batch can still be resolved: fix
# whatever's causing the bulk of exact misses (usually a mapping/
# normalization issue) and rerun 'Full scan' once the count needing a fuzzy
# scan has dropped back under the cap.
FUZZY_SUGGESTION_ROW_LIMIT = 3000


def _programme_for_suggestion(programme: str, time_band: str) -> str:
    return (programme or '').strip() or (time_band or '').strip()


def _attached_timestamp(record) -> float:
    attached_at = getattr(record, 'project_attached_at', None)
    if attached_at is None:
        return 0.0
    if attached_at.tzinfo is None:
        attached_at = attached_at.replace(tzinfo=timezone.utc)
    return attached_at.timestamp()


def _rating_priority(record) -> int:
    # project_ratings_datasets.priority (lower wins), user-orderable via
    # PUT .../ratings-datasets/priority. Missing/None (a rating that isn't
    # project-scoped, e.g. a bare RatingRowRecord from list_rows) sorts as
    # if it were the top priority, same as a freshly-attached dataset
    # before anyone has ever reordered anything.
    priority = getattr(record, 'priority', None)
    return priority if priority is not None else 0


def _rating_order_key(record):
    return (
        _rating_priority(record),
        -_attached_timestamp(record),
        str(getattr(record, 'ratings_dataset_id', '')),
        str(getattr(record, 'id', '')),
    )


def _unmatched_results(unresolved) -> List[ComputedMatch]:
    return [ComputedMatch(activity.id, 'unmatched', None, None, key) for activity, key in unresolved]


def _rating_station_index(rating_records) -> Dict[str, tuple[str, ...]]:
    stations_by_medium: Dict[str, set[str]] = {}
    for rating in rating_records:
        medium = normalize_medium(getattr(rating, 'medium', ''))
        station = normalize_station(getattr(rating, 'station', ''))
        if medium and station:
            stations_by_medium.setdefault(medium, set()).add(station)
    return {medium: tuple(stations) for medium, stations in stations_by_medium.items()}


def _has_station_candidate(medium: str, station: str, stations_by_medium: Dict[str, tuple[str, ...]]) -> bool:
    if not medium or not station:
        return False
    candidate_stations = stations_by_medium.get(medium, ())
    if station in candidate_stations:
        return True
    return any(
        calc.fuzz.token_set_ratio(station, candidate_station) / 100 >= STATION_SUGGESTION_THRESHOLD
        for candidate_station in candidate_stations
    )


def _filter_station_covered_unresolved(unresolved, rating_records):
    stations_by_medium = _rating_station_index(rating_records)
    station_coverage_cache: Dict[tuple[str, str], bool] = {}
    covered = []
    for activity, key in unresolved:
        coverage_key = (
            normalize_medium(getattr(activity, 'medium', '')),
            normalize_station(getattr(activity, 'station', '')),
        )
        if coverage_key not in station_coverage_cache:
            station_coverage_cache[coverage_key] = _has_station_candidate(*coverage_key, stations_by_medium)
        if station_coverage_cache[coverage_key]:
            covered.append((activity, key))
    return covered


@dataclass
class UnmatchedReasonContext:
    """Precomputed once per export call (build_unmatched_reason_context),
    not once per unmatched row -- see that function's docstring for why."""

    has_ratings: bool
    mediums: frozenset
    stations_by_medium: Dict[str, tuple]
    station_days: Dict[tuple, frozenset]


def build_unmatched_reason_context(rating_records) -> UnmatchedReasonContext:
    """Indexes a project's ratings once, for describe_unmatched_reason() to
    reuse across every unmatched row in a match report export.

    Regression: describe_unmatched_reason() used to re-filter and re-index
    the FULL ratings list from scratch on every call, and -- worse -- its
    station-fuzzy-match check ran once per *rating row* sharing a medium
    (not once per distinct station), so a project with many ratings rows
    per station paid a full rapidfuzz comparison per row, per unmatched
    activity row. A real-shaped stress case (15,000 ratings rows across 50
    stations, 2,000 unmatched activity rows with no matching station at
    all -- the worst case, since nothing short-circuits) took over three
    minutes and never returned, which is indistinguishable from a crash to
    a caller: Render's own request/health-check timeout kills the
    connection before any response (including its CORS headers) is ever
    sent, which the browser reports as a CORS failure -- the same red
    herring already documented in services/api/README.md's
    users.avatar_data_url and upload-freeze incidents. Building this index
    once (O(ratings)) and scoring fuzzy-match candidates only against each
    medium's *distinct* stations (bounded, not row-count-based) brings an
    export back down to a fraction of a second at the same scale."""
    mediums: set = set()
    station_days: Dict[tuple, set] = {}
    for rating in rating_records:
        medium = normalize_medium(getattr(rating, 'medium', ''))
        station = normalize_station(getattr(rating, 'station', ''))
        day = normalize_day(getattr(rating, 'day', ''))
        mediums.add(medium)
        station_days.setdefault((medium, station), set()).add(day)
    return UnmatchedReasonContext(
        has_ratings=bool(rating_records),
        mediums=frozenset(mediums),
        stations_by_medium=_rating_station_index(rating_records),
        station_days={key: frozenset(days) for key, days in station_days.items()},
    )


def describe_unmatched_reason(activity, context: UnmatchedReasonContext) -> str:
    """Best-effort, human-readable explanation for why one media_activity
    row never resolved to a rating -- used only by the match report export
    (GET .../matches/export) to answer "why not" for a row the CSV's
    existing Match Status column already says is 'unmatched'. Walks the
    same Medium -> Station -> Day narrowing a user would do by eye,
    reusing the same normalization and fuzzy-station-coverage rules
    compute_matches/_filter_station_covered_unresolved already use, so the
    reason given reflects why neither the exact lookup nor the fuzzy
    suggestion engine found anything, not a generic restatement of
    'unmatched'. Never consulted by matching itself -- purely descriptive.
    Takes a context from build_unmatched_reason_context(), built once per
    export rather than re-derived from the full ratings list on every
    call -- see that function's docstring for why that distinction matters
    at scale."""
    if not context.has_ratings:
        return 'No ratings attached to this project'

    activity_medium = normalize_medium(getattr(activity, 'medium', ''))
    activity_station = normalize_station(getattr(activity, 'station', ''))
    activity_day = normalize_day(getattr(activity, 'day', ''))

    if activity_medium not in context.mediums:
        return f"No ratings for Medium '{activity.medium}'"

    if not _has_station_candidate(activity_medium, activity_station, context.stations_by_medium):
        return f"No rating for Station '{activity.station}' under Medium '{activity.medium}' (or a close match)"

    # Fuzzy-scored against this medium's distinct stations only (typically
    # a handful to a few hundred), never against every rating row sharing
    # one -- the fix for the O(ratings rows) blowup described above.
    candidate_stations = context.stations_by_medium.get(activity_medium, ())
    matching_stations = {
        candidate for candidate in candidate_stations
        if candidate == activity_station
        or calc.fuzz.token_set_ratio(activity_station, candidate) / 100 >= STATION_SUGGESTION_THRESHOLD
    }
    has_day = any(
        activity_day in context.station_days.get((activity_medium, station), ())
        for station in matching_stations
    )
    if not has_day:
        return f"Station matches, but no rating for '{activity.station}' on '{activity.day}'"

    return 'Station and Day match, but no rating entry for this Programme/Time Band'


def compute_matches(media_activity_records, rating_records, *, include_suggestions: bool = True) -> List[ComputedMatch]:
    if not media_activity_records:
        return []

    rating_records = sorted(rating_records, key=_rating_order_key)
    ratings_by_key: Dict[str, object] = {}
    ratings_by_slot: Dict[tuple, List[object]] = {}
    for rating in rating_records:
        key = make_exact_match_key(rating.medium, rating.station, rating.day, rating.programme, rating.time_band)
        ratings_by_key.setdefault(key, rating)  # highest-priority (then newest-attached) dataset wins on duplicate keys
        if is_time_band_range(rating.time_band):
            slot_key = (normalize_medium(rating.medium), normalize_station(rating.station), normalize_day(rating.day))
            ratings_by_slot.setdefault(slot_key, []).append(rating)

    exact_results: List[ComputedMatch] = []
    unresolved = []  # (activity, key)
    for activity in media_activity_records:
        # media_activity.programme already holds the combined "Programme /
        # Time Band" text (see app/parsing.py) — no separate time_band field.
        key = make_exact_match_key(activity.medium, activity.station, activity.day, activity.programme, activity.time_band)
        rating = ratings_by_key.get(key)
        if rating is None:
            slot_key = (normalize_medium(activity.medium), normalize_station(activity.station), normalize_day(activity.day))
            rating = next(
                (
                    candidate for candidate in ratings_by_slot.get(slot_key, [])
                    if time_band_contains(candidate.time_band, activity.time_band)
                ),
                None,
            )
        if rating is not None:
            exact_results.append(ComputedMatch(activity.id, 'exact', rating.id, None, key))
        else:
            unresolved.append((activity, key))

    if not unresolved:
        return exact_results

    if not include_suggestions:
        return exact_results + _unmatched_results(unresolved)

    suggestion_unresolved = _filter_station_covered_unresolved(unresolved, rating_records)
    if len(suggestion_unresolved) > FUZZY_SUGGESTION_ROW_LIMIT:
        logger.warning(
            'Skipping fuzzy suggestion matching for %d rows (limit %d) -- leaving them unmatched. '
            'Fix the underlying mapping/normalization issue causing the bulk exact-miss and rerun '
            "'Full scan' once the count needing a fuzzy scan drops back under the cap.",
            len(suggestion_unresolved), FUZZY_SUGGESTION_ROW_LIMIT,
        )
        suggestion_unresolved = []
    best_suggestion_by_key = _suggest_matches(suggestion_unresolved, rating_records) if suggestion_unresolved else {}

    suggested_results = []
    for activity, key in unresolved:
        suggestion = best_suggestion_by_key.get(key)
        if suggestion is None:
            suggested_results.append(ComputedMatch(activity.id, 'unmatched', None, None, key))
        else:
            rating_id, confidence = suggestion
            suggested_results.append(ComputedMatch(activity.id, 'suggested', rating_id, confidence, key))

    return exact_results + suggested_results


def _suggest_matches(unresolved, rating_records) -> Dict[str, tuple]:
    """Returns {input_match_key: (suggested_rating_id, confidence)} for the
    best (highest-similarity) suggestion per key, using grp_calculator's
    real suggestion engine."""
    if not rating_records:
        return {}

    unique_unresolved = list({key: (activity, key) for activity, key in unresolved}.values())
    media_df = pd.DataFrame({
        'Source File': [a.source_file for a, _ in unique_unresolved],
        'Medium': [a.medium for a, _ in unique_unresolved],
        'Channel / Station': [a.station for a, _ in unique_unresolved],
        'Day': [a.day for a, _ in unique_unresolved],
        'Programme / Time Band': [_programme_for_suggestion(a.programme, a.time_band) for a, _ in unique_unresolved],
        'Time Band': [a.time_band for a, _ in unique_unresolved],
        'Match Key': [key for _, key in unique_unresolved],
        'Match Status': ['NO RATING MATCH'] * len(unique_unresolved),
    })
    ratings_df = pd.DataFrame({
        'Medium': [r.medium for r in rating_records],
        'Channel / Station': [r.station for r in rating_records],
        'Day': [r.day for r in rating_records],
        'Programme / Time Band': [_programme_for_suggestion(r.programme, r.time_band) for r in rating_records],
        'Time Band': [r.time_band for r in rating_records],
        'Rating (%)': [r.rating for r in rating_records],
        'Match Key': [
            make_match_key(r.medium, r.station, r.day, r.programme, r.time_band) for r in rating_records
        ],
    })
    ratings_by_key: Dict[str, object] = {}
    for rating, key in zip(rating_records, ratings_df['Match Key']):
        ratings_by_key.setdefault(key, rating)

    suggestions = calc.build_unmatched_suggestions(media_df, ratings_df)

    best: Dict[str, tuple] = {}
    for _, row in suggestions.iterrows():
        input_key = row['Input Match Key']
        if input_key in best:
            continue  # suggestions are already ordered best-first per input row
        suggested_rating = ratings_by_key.get(row['Suggested Match Key'])
        if suggested_rating is None:
            continue
        best[input_key] = (suggested_rating.id, float(row['Similarity Score']))
    return best
