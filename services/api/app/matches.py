"""Computes rating_matches for media_activity rows against a project's
attached ratings.

Exact matching is a plain dict lookup on the normalized match key (see
app/matching.py) — no need for grp_calculator's DataFrame-merge machinery
just to pick a single rating row per key. Fuzzy suggestions reuse
grp_calculator.build_unmatched_suggestions() directly rather than
reimplementing its candidate-tiering (same medium+channel+day, then
same medium+channel, then same medium+day) and text-similarity scoring.
"""

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
    normalize_station,
    normalize_text,
    time_band_contains,
)


@dataclass
class ComputedMatch:
    media_activity_id: str
    match_status: str  # 'exact' | 'suggested' | 'unmatched'
    matched_rating_id: Optional[str]
    match_confidence: Optional[float]
    match_key: str


STATION_SUGGESTION_THRESHOLD = 0.78


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
        medium = normalize_text(getattr(rating, 'medium', ''))
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
            normalize_text(getattr(activity, 'medium', '')),
            normalize_station(getattr(activity, 'station', '')),
        )
        if coverage_key not in station_coverage_cache:
            station_coverage_cache[coverage_key] = _has_station_candidate(*coverage_key, stations_by_medium)
        if station_coverage_cache[coverage_key]:
            covered.append((activity, key))
    return covered


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
            slot_key = (normalize_text(rating.medium), normalize_station(rating.station), normalize_day(rating.day))
            ratings_by_slot.setdefault(slot_key, []).append(rating)

    exact_results: List[ComputedMatch] = []
    unresolved = []  # (activity, key)
    for activity in media_activity_records:
        # media_activity.programme already holds the combined "Programme /
        # Time Band" text (see app/parsing.py) — no separate time_band field.
        key = make_exact_match_key(activity.medium, activity.station, activity.day, activity.programme, activity.time_band)
        rating = ratings_by_key.get(key)
        if rating is None:
            slot_key = (normalize_text(activity.medium), normalize_station(activity.station), normalize_day(activity.day))
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
