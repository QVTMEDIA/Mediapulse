"""Brand-report, composite-report, and ratings upload parsing, delegating
the real work to grp_calculator.py (imported via the sys.path bootstrap in
app/__init__.py) rather than reimplementing header inference, column-synonym
detection, or the formula-injection/row-limit guards it already has.
"""

import io
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional

import grp_calculator as calc
import pandas as pd

from .schemas.ratings import RatingRowIn

REQUIRED_MAPPING_FIELDS = ('channel', 'programme', 'spots')
OPTIONAL_MAPPING_FIELDS = ('brand', 'medium', 'date', 'day', 'rate', 'cost', 'time_band')

COMPOSITE_REQUIRED_MAPPING_FIELDS = ('channel', 'programme', 'spots')
# 'rating'/'grp' were dropped from here once parse_composite_report switched
# to build_brand_report (see that function's docstring) — build_brand_report
# never reads those mapping keys, so keeping them would just be dead noise
# in the mapping dict (and in the sourceLabel templates saved from it).
COMPOSITE_OPTIONAL_MAPPING_FIELDS = ('brand', 'medium', 'date', 'day', 'rate', 'cost', 'time_band')

RATINGS_REQUIRED_MAPPING_FIELDS = ('channel', 'programme', 'rating')
# 'time_band' lets calc.resolve_effective_programme() fall back to a bare
# time-belt/daypart column when the file has no distinct Programme name at
# all (real radio audience-reach data commonly doesn't) — 'programme'
# itself stays required so the field is always in the mapping dict, but its
# resolved *value* can now come from time_band when the programme column
# wasn't found or is blank on a given row.
RATINGS_OPTIONAL_MAPPING_FIELDS = ('medium', 'source', 'time_band', 'date', 'day')


class NamedBytesIO(io.BytesIO):
    """grp_calculator's readers expect a file-like object with a `.name`
    (as Streamlit's UploadedFile provides) — FastAPI's UploadFile.file
    doesn't have one, so this adapts a plain byte buffer to look like one."""

    def __init__(self, data: bytes, name: str):
        super().__init__(data)
        self.name = name


@dataclass
class MappingWarning:
    """A saved mapping template pinned `field` to `template_column`, but this
    file's own columns would have auto-detected `detected_column` instead --
    a real, previously-silent trap: a template saved from one file's shape
    (e.g. a vendor's older export with only a coarse "TIME BELT" AM/PM
    column) gets reused against a newer file that actually has a better
    match (e.g. a precise "TIMEBAND" clock-time column) sitting right next
    to it, and the stale template wins with no indication anything was
    overridden. Every row still parses "successfully" -- the failure only
    shows up much later as spot after spot coming back unmatched, with
    nothing on the upload response pointing back at the cause."""

    field: str
    template_column: str
    detected_column: str


def _resolve_mapping(columns, expected_fields, overrides: Optional[Dict[str, str]] = None):
    """Auto-detects a column per logical field, same as before, except a
    field present in `overrides` (a saved mapping template) skips detection
    and uses that column directly — as long as the column still exists in
    this particular file; a stale template pointing at a renamed/missing
    column falls back to auto-detection for that field rather than erroring.

    Also always runs detection alongside the override (cheap — it's a
    synonym lookup over a short column list) so a field where the two
    disagree comes back as a MappingWarning instead of disappearing
    silently. No warning when detection finds nothing at all: a template
    column with no synonym match in this file (a custom header the
    synonym list was never going to recognize) is the normal, correct
    reason overrides exist in the first place, not something to flag.

    Returns (mapping, warnings) — warnings is always [] when overrides is
    empty, since there's nothing to disagree with."""
    overrides = overrides or {}
    mapping = {}
    warnings: List[MappingWarning] = []
    for field in expected_fields:
        override_column = overrides.get(field)
        detected_column = calc.detect_column(columns, field)
        if override_column and override_column in columns:
            mapping[field] = override_column
            if detected_column and detected_column != override_column:
                warnings.append(MappingWarning(field=field, template_column=override_column, detected_column=detected_column))
        else:
            mapping[field] = detected_column or '-- none --'
    return mapping, warnings


@dataclass
class ParsedMediaRow:
    medium: str
    station: str
    activity_date: Optional[date]
    day: str
    programme: str
    spots: int
    source_file: str
    source_row_number: Optional[int]
    cost: Optional[float] = None
    time_band: str = ''


@dataclass
class ParseResult:
    rows: List[ParsedMediaRow]
    mapping: dict
    mapped_rows: int
    issue_rows: int
    mapping_warnings: List[MappingWarning]


def parse_brand_report(
    data: bytes, file_name: str, default_medium: str = 'TV', mapping_override: Optional[Dict[str, str]] = None
) -> ParseResult:
    """Raises ValueError (via grp_calculator's own validation) on anything
    it can't read — callers should turn that into a 422."""
    uploaded = NamedBytesIO(data, file_name)
    calc.validate_uploaded_file(uploaded)

    expected_fields = list(REQUIRED_MAPPING_FIELDS) + list(OPTIONAL_MAPPING_FIELDS)
    preview = calc.read_preview_table(uploaded)
    if preview.empty:
        raise ValueError('The uploaded file does not contain any readable rows.')
    header_row = calc.infer_header_row(preview, expected_fields)
    raw = calc.read_tabular(uploaded, header_row=header_row)

    mapping, mapping_warnings = _resolve_mapping(raw.columns, expected_fields, mapping_override)
    report, issues = calc.build_brand_report(raw, mapping, file_name, default_medium)

    rows = [
        ParsedMediaRow(
            medium=row['Medium'],
            station=row['Channel / Station'],
            activity_date=_clean_date(row['Date']),
            day=str(row['Day'] or ''),
            programme=row['Programme / Time Band'],
            spots=int(row['Spots']),
            source_file=file_name,
            source_row_number=None,  # dropped by build_brand_report's issue-filtering; not worth re-deriving yet
            cost=_clean_cost(row['Cost']),
            time_band=str(row['Daypart'] or ''),
        )
        for _, row in report.iterrows()
    ]
    return ParseResult(
        rows=rows, mapping=mapping, mapped_rows=len(rows), issue_rows=len(issues), mapping_warnings=mapping_warnings
    )


@dataclass
class ParsedCompositeRow:
    brand_name: str
    medium: str
    station: str
    activity_date: Optional[date]
    day: str
    programme: str
    spots: int
    source_file: str
    cost: Optional[float] = None
    time_band: str = ''


@dataclass
class CompositeParseResult:
    rows: List[ParsedCompositeRow]
    mapping: dict
    mapped_rows: int
    issue_rows: int
    mapping_warnings: List[MappingWarning]


def parse_composite_report(
    data: bytes, file_name: str, default_medium: str = 'TV', mapping_override: Optional[Dict[str, str]] = None
) -> CompositeParseResult:
    """Like parse_brand_report, but multi-brand: reads a Brand column per row
    (falling back to the filename-inferred brand when a row's Brand is
    blank), rather than trusting a single caller-supplied brand for the
    whole file.

    Deliberately reuses grp_calculator.build_brand_report(), not
    build_composite_report() — despite the matching name, that function
    implements app.py's different "Composite Report" concept: one workbook
    that already carries a vendor's own pre-computed Rating/GRP per row, and
    it rejects any row missing both. This API's composite_report upload
    kind is a raw, multi-brand spot list — ratings get matched afterward by
    the Matching Engine, exactly like a brand_report upload, so requiring
    Rating/GRP up front was always wrong for this pipeline. It went
    unnoticed because build_brand_report already reads a per-row Brand
    column the same way (with the same filename-fallback) whenever mapping
    includes 'brand' — the two builders only ever differed in this
    Rating/GRP requirement, not in brand handling — until a real
    multi-brand vendor file with no Rating/GRP column at all (just
    Station/Spots/Rate) came back with every single row flagged as an
    issue. See CHANGELOG.md."""
    uploaded = NamedBytesIO(data, file_name)
    calc.validate_uploaded_file(uploaded)

    expected_fields = list(COMPOSITE_REQUIRED_MAPPING_FIELDS) + list(COMPOSITE_OPTIONAL_MAPPING_FIELDS)
    preview = calc.read_preview_table(uploaded)
    if preview.empty:
        raise ValueError('The uploaded file does not contain any readable rows.')
    header_row = calc.infer_header_row(preview, expected_fields)
    raw = calc.read_tabular(uploaded, header_row=header_row)

    mapping, mapping_warnings = _resolve_mapping(raw.columns, expected_fields, mapping_override)
    report, issues = calc.build_brand_report(raw, mapping, file_name, default_medium)

    rows = [
        ParsedCompositeRow(
            brand_name=str(row['Brand'] or '').strip(),
            medium=row['Medium'],
            station=row['Channel / Station'],
            activity_date=_clean_date(row['Date']),
            day=str(row['Day'] or ''),
            programme=row['Programme / Time Band'],
            spots=int(row['Spots']),
            source_file=file_name,
            cost=_clean_cost(row['Cost']),
            time_band=str(row['Daypart'] or ''),
        )
        for _, row in report.iterrows()
        if str(row['Brand'] or '').strip()
    ]
    return CompositeParseResult(
        rows=rows, mapping=mapping, mapped_rows=len(rows), issue_rows=len(issues), mapping_warnings=mapping_warnings
    )


@dataclass
class RatingsRowIssue:
    """One dropped row's actual explanation — grp_calculator.build_ratings_
    lookup() already computes exactly this (row number, reason, and the
    field values that led to it) via issue_frame(), but parse_ratings_file
    used to discard everything except a bare count. A file that rejects
    every row (a real incident: 134/134 dropped, 0 stored) gave no way to
    tell "the Rating column wasn't detected at all" from "every rating
    happened to be out of range" from "the Day column is blank" without
    downloading and inspecting the source file by hand."""

    row_number: int
    reason: str
    medium: str
    station: str
    day: str
    programme: str
    rating: Optional[float]


@dataclass
class RatingsParseResult:
    rows: List[RatingRowIn]
    mapping: dict
    # Rows grp_calculator's own validation (missing match field, or rating
    # out of 0-100 range) dropped before they ever became a RatingRowIn —
    # stricter than RatingRowIn's own looser validity check, so these are
    # never silently absorbed into a 0 via the usual invalid-row counting.
    dropped_invalid_rows: int
    issues: List[RatingsRowIssue]
    mapping_warnings: List[MappingWarning]


def parse_ratings_file(
    data: bytes, file_name: str, default_medium: str = 'TV', mapping_override: Optional[Dict[str, str]] = None
) -> RatingsParseResult:
    """Raises ValueError (via grp_calculator's own validation) on anything
    it can't read — callers should turn that into a 422."""
    uploaded = NamedBytesIO(data, file_name)
    calc.validate_uploaded_file(uploaded)

    expected_fields = list(RATINGS_REQUIRED_MAPPING_FIELDS) + list(RATINGS_OPTIONAL_MAPPING_FIELDS)
    preview = calc.read_preview_table(uploaded)
    if preview.empty:
        raise ValueError('The uploaded file does not contain any readable rows.')
    header_row = calc.infer_header_row(preview, expected_fields)
    raw = calc.read_tabular(uploaded, header_row=header_row)

    mapping, mapping_warnings = _resolve_mapping(raw.columns, expected_fields, mapping_override)
    ratings, invalid_ratings, _dup_keys, _lookup = calc.build_ratings_lookup(raw, mapping, default_medium)

    rows = [
        RatingRowIn(
            medium=row['Medium'],
            station=row['Channel / Station'],
            day=row['Day'],
            programme=row['Programme / Time Band'],
            time_band=str(row['Time Band'] or '').strip(),
            rating=float(row['Rating (%)']) if pd.notna(row['Rating (%)']) else None,
        )
        for _, row in ratings.iterrows()
    ]
    issues = [
        RatingsRowIssue(
            row_number=int(row['Input Row']),
            reason=row['Issue'],
            medium=str(row['Medium'] or ''),
            station=str(row['Channel / Station'] or ''),
            day=str(row['Day'] or ''),
            programme=str(row['Programme / Time Band'] or ''),
            rating=float(row['Rating (%)']) if pd.notna(row['Rating (%)']) else None,
        )
        for _, row in invalid_ratings.iterrows()
    ]
    return RatingsParseResult(
        rows=rows, mapping=mapping, dropped_invalid_rows=len(invalid_ratings), issues=issues,
        mapping_warnings=mapping_warnings,
    )


def _clean_cost(value) -> Optional[float]:
    # NaN means no cost/rate column was ever mapped for this row (or the
    # mapped cell itself was blank) — None, not 0.0, for the same reason
    # grp_calculator.resolve_row_cost() returns NaN rather than 0 there:
    # "no spend data" and "confirmed zero spend" aren't the same fact.
    if pd.isna(value):
        return None
    return float(value)


def _clean_date(value) -> Optional[date]:
    if pd.isna(value) or str(value).strip() == '':
        return None
    # ISO (YYYY-MM-DD) is unambiguous — parsed first, separately, for the
    # same reason grp_calculator.derive_day() now does the same (see its
    # comment): dayfirst=True below silently misreads an ISO date whenever
    # day and month are both <=12 (e.g. "2026-01-05" becomes May 1st).
    try:
        return pd.to_datetime(value, format='%Y-%m-%d').date()
    except (ValueError, TypeError):
        pass
    try:
        return pd.to_datetime(value, dayfirst=True).date()
    except (ValueError, TypeError):
        return None
