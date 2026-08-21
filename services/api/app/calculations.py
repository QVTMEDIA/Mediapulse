"""GRP run calculation: joins persisted media_activity + rating_matches +
ratings into per-row GRPs and a per-brand rollup, reusing
grp_calculator.summarize_media() for the TV/Radio/Total GRP and SOV
aggregation rather than reimplementing that grouping logic.

Row GRP = Spots x Rating, for rows with a resolved rating only. Unmatched
rows (or a manual correction with no rating, or one pointing at a rating
whose own value is null) are counted in `unmatched_rows` but never get a
grp_calculations row — db/schema.sql makes `grp` NOT NULL there on purpose,
because "no rating" and "confirmed zero GRP" are different things and the
schema shouldn't blur them.
"""

from dataclasses import dataclass
from datetime import date as date_type
from typing import Dict, List, Optional

import grp_calculator as calc
import pandas as pd


@dataclass
class CalculatedRow:
    media_activity_id: str
    rating_match_id: str
    spots: int
    rating: float
    grp: float
    # Not columns on grp_calculations (db/schema.sql keeps that table to the
    # bare calculation) — carried here so the spot-level read route and the
    # station/programme/trend routes don't need a second repository
    # dependency just to label or group each row. Postgres re-derives these
    # via a JOIN on read instead of trusting a stored copy;
    # InMemoryCalculationsRepository stores them as-is since it has no join.
    brand_id: str
    station: str
    programme: str
    day: str
    medium: str
    activity_date: Optional[date_type]


@dataclass
class BrandShareResult:
    brand_id: str
    total_grps: float
    tv_grps: float
    radio_grps: float
    sov: float
    spots: int
    avg_rating: Optional[float]
    # Share of Expenditure — see the comment on brand_shares.total_spend in
    # db/schema.sql for why this is summed from every one of the brand's
    # media_activity rows, not just the matched/calculable ones GRP uses.
    total_spend: float
    soe: float


@dataclass
class RunResult:
    total_brands: int
    total_spots: int
    total_grps: float
    total_spend: float
    matched_rows: int
    unmatched_rows: int
    calculated_rows: List[CalculatedRow]
    brand_shares: List[BrandShareResult]


EMPTY_RUN = RunResult(0, 0, 0.0, 0.0, 0, 0, [], [])


def compute_run(media_activity_records, match_by_activity_id: Dict[str, object], rating_by_id: Dict[str, object]) -> RunResult:
    if not media_activity_records:
        return EMPTY_RUN

    calculated_rows: List[CalculatedRow] = []
    ratings_by_brand: Dict[str, List[float]] = {}
    spend_by_brand: Dict[str, float] = {}
    calc_frame_records = []
    matched_rows = 0
    unmatched_rows = 0

    for activity in media_activity_records:
        match = match_by_activity_id.get(activity.id)
        rating_record = rating_by_id.get(match.matched_rating_id) if match and match.matched_rating_id else None
        rating_value = rating_record.rating if rating_record is not None else None
        is_calculable = match is not None and match.match_status != 'unmatched' and rating_value is not None

        if is_calculable:
            rating_value = float(rating_value)
            grp = activity.spots * rating_value
            matched_rows += 1
            calculated_rows.append(CalculatedRow(
                media_activity_id=activity.id, rating_match_id=match.id, spots=activity.spots,
                rating=rating_value, grp=grp, brand_id=activity.brand_id, station=activity.station,
                programme=activity.programme, day=activity.day, medium=activity.medium,
                activity_date=activity.activity_date,
            ))
            ratings_by_brand.setdefault(activity.brand_id, []).append(rating_value)
        else:
            unmatched_rows += 1
            grp = None

        # Spend is summed for every row regardless of is_calculable — money
        # was spent on a spot whether or not a rating was ever found for
        # it, unlike GRP, which only exists for matched rows. A row with no
        # cost/rate ever mapped has activity.cost = None, contributing 0.
        if activity.cost is not None:
            spend_by_brand[activity.brand_id] = spend_by_brand.get(activity.brand_id, 0.0) + activity.cost

        calc_frame_records.append({
            'Brand': activity.brand_id,
            'Medium': activity.medium,
            'Spots': activity.spots,
            'GRP': grp,
            'Match Status': 'MATCHED' if is_calculable else 'NO RATING MATCH',
        })

    media_df = pd.DataFrame(calc_frame_records)
    summary_df, category_grps, _suspicious_mediums = calc.summarize_media(media_df)
    category_spend = sum(spend_by_brand.values())

    brand_shares = []
    for _, row in summary_df.iterrows():
        brand_id = row['Brand']
        ratings = ratings_by_brand.get(brand_id, [])
        brand_spend = spend_by_brand.get(brand_id, 0.0)
        brand_shares.append(BrandShareResult(
            brand_id=brand_id,
            total_grps=float(row['Total GRPs']),
            tv_grps=float(row['TV GRPs']),
            radio_grps=float(row['Radio GRPs']),
            sov=float(row['GRP SOV']) * 100,
            spots=int(row['Total Spots']),
            avg_rating=(sum(ratings) / len(ratings)) if ratings else None,
            total_spend=brand_spend,
            soe=(brand_spend / category_spend * 100) if category_spend else 0.0,
        ))

    return RunResult(
        total_brands=len(brand_shares),
        total_spots=int(media_df['Spots'].sum()),
        total_spend=category_spend,
        total_grps=float(category_grps) if category_grps else 0.0,
        matched_rows=matched_rows,
        unmatched_rows=unmatched_rows,
        calculated_rows=calculated_rows,
        brand_shares=brand_shares,
    )
