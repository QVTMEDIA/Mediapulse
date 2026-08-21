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
OPTIONAL_MAPPING_FIELDS = ('brand', 'medium', 'date', 'day')

COMPOSITE_REQUIRED_MAPPING_FIELDS = ('channel', 'programme', 'spots')
COMPOSITE_OPTIONAL_MAPPING_FIELDS = ('brand', 'medium', 'date', 'day', 'rating', 'grp')

RATINGS_REQUIRED_MAPPING_FIELDS = ('channel', 'day', 'programme', 'rating')
RATINGS_OPTIONAL_MAPPING_FIELDS = ('medium', 'source')


class NamedBytesIO(io.BytesIO):
    """grp_calculator's readers expect a file-like object with a `.name`
    (as Streamlit's UploadedFile provides) — FastAPI's UploadFile.file
    doesn't have one, so this adapts a plain byte buffer to look like one."""

    def __init__(self, data: bytes, name: str):
        super().__init__(data)
        self.name = name


def _resolve_mapping(columns, expected_fields, overrides: Optional[Dict[str, str]] = None) -> dict:
    """Auto-detects a column per logical field, same as before, except a
    field present in `overrides` (a saved mapping template) skips detection
    and uses that column directly — as long as the column still exists in
    this particular file; a stale template pointing at a renamed/missing
    column falls back to auto-detection for that field rather than erroring."""
    overrides = overrides or {}
    mapping = {}
    for field in expected_fields:
        override_column = overrides.get(field)
        if override_column and override_column in columns:
            mapping[field] = override_column
        else:
            mapping[field] = calc.detect_column(columns, field) or '-- none --'
    return mapping


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


@dataclass
class ParseResult:
    rows: List[ParsedMediaRow]
    mapping: dict
    mapped_rows: int
    issue_rows: int


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

    mapping = _resolve_mapping(raw.columns, expected_fields, mapping_override)
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
        )
        for _, row in report.iterrows()
    ]
    return ParseResult(rows=rows, mapping=mapping, mapped_rows=len(rows), issue_rows=len(issues))


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


@dataclass
class CompositeParseResult:
    rows: List[ParsedCompositeRow]
    mapping: dict
    mapped_rows: int
    issue_rows: int


def parse_composite_report(
    data: bytes, file_name: str, default_medium: str = 'TV', mapping_override: Optional[Dict[str, str]] = None
) -> CompositeParseResult:
    """Like parse_brand_report, but multi-brand: grp_calculator.
    build_composite_report() reads the Brand column itself (falling back to
    the filename when a row has none), rather than trusting a single
    caller-supplied brand for the whole file. The uploaded Rating/GRP
    columns are read by grp_calculator for its own row-validation but not
    carried into the result — this API's calculate pipeline is the one
    source of truth for GRP, not whatever a monitoring vendor already
    computed. Note this means a row needs a usable Rating or GRP value to
    validate at all (grp_calculator's definition of a composite report,
    unlike a brand_report's raw spot list) — a file with neither column
    will come back with every row flagged as an issue and nothing stored."""
    uploaded = NamedBytesIO(data, file_name)
    calc.validate_uploaded_file(uploaded)

    expected_fields = list(COMPOSITE_REQUIRED_MAPPING_FIELDS) + list(COMPOSITE_OPTIONAL_MAPPING_FIELDS)
    preview = calc.read_preview_table(uploaded)
    if preview.empty:
        raise ValueError('The uploaded file does not contain any readable rows.')
    header_row = calc.infer_header_row(preview, expected_fields)
    raw = calc.read_tabular(uploaded, header_row=header_row)

    mapping = _resolve_mapping(raw.columns, expected_fields, mapping_override)
    report, issues = calc.build_composite_report(raw, mapping, file_name, default_medium)

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
        )
        for _, row in report.iterrows()
        if str(row['Brand'] or '').strip()
    ]
    return CompositeParseResult(rows=rows, mapping=mapping, mapped_rows=len(rows), issue_rows=len(issues))


@dataclass
class RatingsParseResult:
    rows: List[RatingRowIn]
    mapping: dict
    # Rows grp_calculator's own validation (missing match field, or rating
    # out of 0-100 range) dropped before they ever became a RatingRowIn —
    # stricter than RatingRowIn's own looser validity check, so these are
    # never silently absorbed into a 0 via the usual invalid-row counting.
    dropped_invalid_rows: int


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

    mapping = _resolve_mapping(raw.columns, expected_fields, mapping_override)
    ratings, invalid_ratings, _dup_keys, _lookup = calc.build_ratings_lookup(raw, mapping, default_medium)

    rows = [
        RatingRowIn(
            medium=row['Medium'],
            station=row['Channel / Station'],
            day=row['Day'],
            programme=row['Programme / Time Band'],
            rating=float(row['Rating (%)']) if pd.notna(row['Rating (%)']) else None,
        )
        for _, row in ratings.iterrows()
    ]
    return RatingsParseResult(rows=rows, mapping=mapping, dropped_invalid_rows=len(invalid_ratings))


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
