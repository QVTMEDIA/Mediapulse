"""Builds the full Excel export workbook, per the sheet structure documented
in PRODUCT_ROADMAP.md's "Export workbook structure": Project Info /
Executive Summary, GRP & SOV, Brand Comparison, Station Performance,
Programme Performance, Spot-Level Calculations, Unmatched Records, Ratings
Used.

Unlike the Streamlit app's export (app.py), this doesn't reuse
grp_calculator's build_run_summary/project_info_frame helpers — those are
shaped around a single in-session pandas DataFrame with Streamlit-specific
derived columns, not the normalized Postgres-backed records this service
already has from its own repositories. Building fresh, simpler DataFrames
directly from plain dicts (assembled by app/routers/exports.py, which is
the layer that already knows how to join a brand_id to a brand name) is
less code than adapting the Streamlit shape to fit.
"""

import io
from typing import List, Optional

import pandas as pd

TEMPLATE_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def build_workbook(
    *,
    project,
    run,
    brand_shares: List[dict],
    calculations: List[dict],
    station_shares: List[dict],
    programme_shares: List[dict],
    unmatched_rows: List[dict],
    ratings_rows: List[dict],
    generated_at: str,
) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        _project_info_sheet(writer, project, run, generated_at)
        _grp_sov_sheet(writer, brand_shares)
        _brand_comparison_sheet(writer, brand_shares)
        _dimension_sheet(writer, station_shares, 'Station Performance', 'Station')
        _dimension_sheet(writer, programme_shares, 'Programme Performance', 'Programme')
        _spot_level_sheet(writer, calculations)
        _unmatched_sheet(writer, unmatched_rows)
        _ratings_sheet(writer, ratings_rows)
    output.seek(0)
    return output.getvalue()


def _write(writer, df: pd.DataFrame, columns: List[str], sheet_name: str):
    if df.empty:
        df = pd.DataFrame(columns=columns)
    # Excel sheet names cap at 31 chars and reject some punctuation — every
    # name used here is already short and plain, but truncate defensively
    # rather than letting openpyxl raise on a future rename.
    df.to_excel(writer, sheet_name=sheet_name[:31], index=False)


def _project_info_sheet(writer, project, run, generated_at: str):
    rows = [
        ('Project', project.name),
        ('Client', project.client or ''),
        ('Category', project.category or ''),
        ('Market', project.market or ''),
        ('Start Date', str(project.start_date) if project.start_date else ''),
        ('End Date', str(project.end_date) if project.end_date else ''),
        ('Target Audience', project.target_audience or ''),
        ('Media Types', ', '.join(project.media_types or [])),
        ('Ratings Provider', project.ratings_provider or ''),
        ('Status', project.status),
        ('Report Generated', generated_at),
    ]
    if run is not None:
        rows += [
            ('Run ID', run.id),
            ('Run Generated At', str(run.generated_at)),
            ('Total Brands', run.total_brands),
            ('Total Spots', run.total_spots),
            ('Total GRPs', round(run.total_grps, 2)),
            ('Total Spend', round(run.total_spend, 2)),
            ('Matched Rows', run.matched_rows),
            ('Unmatched Rows', run.unmatched_rows),
        ]
    else:
        rows.append(('Run', 'No calculation has been run for this project yet.'))
    _write(writer, pd.DataFrame(rows, columns=['Field', 'Value']), ['Field', 'Value'], 'Project Info')


def _grp_sov_sheet(writer, brand_shares: List[dict]):
    ordered = sorted(brand_shares, key=lambda s: s['total_grps'], reverse=True)
    df = pd.DataFrame([
        {
            'Brand': share['brand'],
            'Total GRPs': round(share['total_grps'], 2),
            'TV GRPs': round(share['tv_grps'], 2),
            'Cable TV GRPs': round(share['cable_tv_grps'], 2),
            'Radio GRPs': round(share['radio_grps'], 2),
            'SOV %': round(share['sov'], 1),
            'Spots': share['spots'],
            'Avg Rating': round(share['avg_rating'], 2) if share['avg_rating'] is not None else None,
            'Spend': round(share['total_spend'], 2),
            'SOE %': round(share['soe'], 1),
        }
        for share in ordered
    ])
    _write(
        writer, df,
        ['Brand', 'Total GRPs', 'TV GRPs', 'Cable TV GRPs', 'Radio GRPs', 'SOV %', 'Spots', 'Avg Rating', 'Spend', 'SOE %'],
        'GRP & SOV',
    )


def _brand_comparison_sheet(writer, brand_shares: List[dict]):
    # Every brand side by side, metric-as-row / brand-as-column — the same
    # data as "GRP & SOV" transposed, so it reads as a comparison table
    # rather than a ranked list (mirrors the Reports screen's brand-vs-brand
    # picker in packages/web, just for every brand at once instead of two).
    ordered = sorted(brand_shares, key=lambda s: s['total_grps'], reverse=True)
    metrics = ['Total GRPs', 'TV GRPs', 'Cable TV GRPs', 'Radio GRPs', 'SOV %', 'Spots', 'Avg Rating', 'Spend', 'SOE %']
    data = {'Metric': metrics}
    for share in ordered:
        data[share['brand']] = [
            round(share['total_grps'], 2),
            round(share['tv_grps'], 2),
            round(share['cable_tv_grps'], 2),
            round(share['radio_grps'], 2),
            round(share['sov'], 1),
            share['spots'],
            round(share['avg_rating'], 2) if share['avg_rating'] is not None else None,
            round(share['total_spend'], 2),
            round(share['soe'], 1),
        ]
    df = pd.DataFrame(data) if ordered else pd.DataFrame({'Metric': metrics})
    df.to_excel(writer, sheet_name='Brand Comparison', index=False)


def _dimension_sheet(writer, shares: List[dict], sheet_name: str, dimension_label: str):
    dimension_key = dimension_label.lower()
    ordered = sorted(shares, key=lambda s: s['total_grps'], reverse=True)
    df = pd.DataFrame([
        {'Brand': s['brand'], dimension_label: s[dimension_key], 'Total GRPs': round(s['total_grps'], 2), 'Spots': s['spots']}
        for s in ordered
    ])
    _write(writer, df, ['Brand', dimension_label, 'Total GRPs', 'Spots'], sheet_name)


def _spot_level_sheet(writer, calculations: List[dict]):
    df = pd.DataFrame([
        {
            'Brand': row['brand'], 'Station': row['station'], 'Programme': row['programme'], 'Day': row['day'],
            'Medium': row['medium'], 'Spots': row['spots'], 'Rating': round(row['rating'], 2),
            'GRP': round(row['grp'], 2), 'Calculated At': str(row['calculated_at']),
        }
        for row in calculations
    ])
    _write(writer, df, ['Brand', 'Station', 'Programme', 'Day', 'Medium', 'Spots', 'Rating', 'GRP', 'Calculated At'], 'Spot-Level Calculations')


def _unmatched_sheet(writer, unmatched_rows: List[dict]):
    df = pd.DataFrame([
        {
            'Brand': row['brand'], 'Medium': row['medium'], 'Station': row['station'],
            'Programme': row['programme'], 'Day': row['day'], 'Spots': row['spots'],
            'Match Status': row['match_status'],
        }
        for row in unmatched_rows
    ])
    _write(writer, df, ['Brand', 'Medium', 'Station', 'Programme', 'Day', 'Spots', 'Match Status'], 'Unmatched Records')


def _ratings_sheet(writer, ratings_rows: List[dict]):
    df = pd.DataFrame([
        {
            'Medium': row['medium'], 'Station': row['station'], 'Day': row['day'],
            'Programme': row['programme'] or '', 'Time Band': row['time_band'] or '', 'Rating': row['rating'],
        }
        for row in ratings_rows
    ])
    _write(writer, df, ['Medium', 'Station', 'Day', 'Programme', 'Time Band', 'Rating'], 'Ratings Used')
