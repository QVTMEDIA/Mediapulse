import math
import re
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

DAY_MAP = {
    'monday': 'MON', 'mon': 'MON',
    'tuesday': 'TUE', 'tue': 'TUE', 'tues': 'TUE',
    'wednesday': 'WED', 'wed': 'WED',
    'thursday': 'THU', 'thu': 'THU', 'thur': 'THU', 'thurs': 'THU',
    'friday': 'FRI', 'fri': 'FRI',
    'saturday': 'SAT', 'sat': 'SAT',
    'sunday': 'SUN', 'sun': 'SUN',
}

SYNONYMS = {
    'brand': ['brand', 'advertiser', 'client', 'product'],
    'medium': ['medium', 'media', 'media type', 'media_type', 'media class', 'media category'],
    'date': ['date', 'air date', 'airdate', 'broadcast date'],
    'day': ['day', 'weekday', 'day of week', 'wd', 'dow', 'week day'],
    'channel': ['channel / station', 'channel', 'station', 'media channel', 'tv station', 'radio station', 'network', 'vehicle'],
    'programme': ['programme / time band', 'program / time band', 'programme', 'program', 'programme title', 'program title', 'title', 'time band', 'timeband', 'daypart', 'slot', 'time slot', 'time'],
    'spots': ['spots', 'spot', 'no. of spots', 'no spots', 'number of spots', 'spot count', 'insertions', 'frequency', 'qty', 'quantity', 'runs', 'count'],
    'rating': ['rating (%)', 'rating', 'ratings', 'program rating', 'programme rating', 'rating %', 'rch %', 'rch%', 'reach %', 'reach%', 'tvr', 'tvrs', 'grp', 'grps'],
    'grp': ['grp', 'grps', 'gross rating points', 'gross rating point', 'row grp', 'total grp', 'total grps'],
    'source': ['source / period', 'source', 'period', 'wave', 'survey period'],
}

TEMPLATE_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
EXCEL_FORMULA_PREFIXES = ('=', '+', '-', '@')
ALLOWED_UPLOAD_TYPES = ['xlsx', 'xls', 'csv']
ALLOWED_UPLOAD_SUFFIXES = tuple(f'.{ext}' for ext in ALLOWED_UPLOAD_TYPES)
MAX_UPLOAD_SIZE_MB = 10
MAX_UPLOAD_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024
MAX_UPLOAD_ROWS = 100_000
MAX_UPLOAD_COLUMNS = 100
AUTH_SESSION_TIMEOUT_SECONDS = 8 * 60 * 60
AUTH_MAX_FAILED_ATTEMPTS = 5
AUTH_LOCKOUT_SECONDS = 5 * 60
SUGGESTION_COLUMNS = [
    'Brand',
    'Source File',
    'Input Medium',
    'Input Channel / Station',
    'Input Day',
    'Input Programme / Time Band',
    'Suggested Channel / Station',
    'Suggested Day',
    'Suggested Programme / Time Band',
    'Suggested Rating (%)',
    'Similarity Score',
    'Confidence',
    'Suggestion Basis',
    'Input Match Key',
    'Suggested Match Key',
]
PROJECT_METADATA_LABELS = {
    'project_id': 'Project ID',
    'project_name': 'Project Name',
    'client': 'Client',
    'category': 'Category',
    'market': 'Market',
    'start_date': 'Start Date',
    'end_date': 'End Date',
    'target_audience': 'Target Audience',
    'media_types': 'Media Types',
    'ratings_provider': 'Ratings Provider',
    'ratings_period': 'Ratings Period',
    'status': 'Project Status',
    'notes': 'Notes',
}
TEMPLATE_DEFINITIONS = {
    'ratings': (
        'Ratings Template',
        {
            'Medium': 'TV',
            'Channel / Station': 'Sample Station',
            'Day': 'Mon',
            'Programme / Time Band': '20:00-20:15',
            'Rating (%)': 2.5,
            'Source / Period': 'Sample wave',
        },
    ),
    'brand': (
        'Brand Report Template',
        {
            'Brand': 'Sample Brand',
            'Medium': 'TV',
            'Date': '',
            'Day': 'Mon',
            'Channel / Station': 'Sample Station',
            'Programme / Time Band': '20:00-20:15',
            'Spots': 1,
        },
    ),
    'composite': (
        'Composite Template',
        {
            'Brand': 'Sample Brand',
            'Medium': 'TV',
            'Date': '',
            'WD': 'Mon',
            'Channel': 'Sample Station',
            'Program': '20:00-20:15',
            'Spots': 1,
            'Rch %': 2.5,
            'Grps': 2.5,
        },
    ),
}


def canon(s):
    return re.sub(r'\s+', ' ', str(s).strip()).lower()


def template_dataframe(kind):
    if kind not in TEMPLATE_DEFINITIONS:
        supported = ', '.join(sorted(TEMPLATE_DEFINITIONS))
        raise ValueError(f'Unknown template "{kind}". Supported templates: {supported}.')
    sheet_name, row = TEMPLATE_DEFINITIONS[kind]
    return pd.DataFrame([row]), sheet_name


def project_info_frame(project_info):
    project_info = project_info or {}
    rows = []
    for key, label in PROJECT_METADATA_LABELS.items():
        value = project_info.get(key, '')
        if isinstance(value, (list, tuple, set)):
            value = ', '.join(str(item) for item in value if str(item).strip())
        rows.append({'Field': label, 'Value': value})
    return pd.DataFrame(rows)


def detect_column(columns, logical):
    cols = {canon(c): c for c in columns}
    for syn in SYNONYMS[logical]:
        if canon(syn) in cols:
            return cols[canon(syn)]
    for c in columns:
        cc = canon(c)
        if any(canon(syn) in cc or cc in canon(syn) for syn in SYNONYMS[logical]):
            return c
    return None


def normalize_text(v):
    if pd.isna(v):
        return ''
    return re.sub(r'\s+', ' ', str(v).strip()).upper()


def text_similarity(left, right):
    left_norm = normalize_text(left)
    right_norm = normalize_text(right)
    if not left_norm or not right_norm:
        return 0.0
    return float(SequenceMatcher(None, left_norm, right_norm).ratio())


def suggestion_confidence(score):
    if score >= 0.9:
        return 'High'
    if score >= 0.7:
        return 'Medium'
    return 'Low'


def normalize_medium_type(v):
    s = normalize_text(v)
    aliases = {
        'TV': 'TV',
        'TELEVISION': 'TV',
        'TELLY': 'TV',
        'RADIO': 'RADIO',
        'FM RADIO': 'RADIO',
        'AM RADIO': 'RADIO',
    }
    if s in aliases:
        return aliases[s]
    if 'TELEVISION' in s or re.search(r'\bTV\b', s):
        return 'TV'
    if 'RADIO' in s:
        return 'RADIO'
    return 'OTHER' if s else 'MISSING'


def normalize_day(v):
    if pd.isna(v) or str(v).strip() == '':
        return ''
    s = str(v).strip().lower()
    if s in DAY_MAP:
        return DAY_MAP[s]
    s3 = s[:3]
    for k, val in DAY_MAP.items():
        if k[:3] == s3:
            return val
    return normalize_text(v)[:3]


def derive_day(date_series):
    dt = pd.to_datetime(date_series, errors='coerce', dayfirst=True)
    return dt.dt.day_name().str[:3].str.upper().fillna('')


def uploaded_display_name(uploaded):
    return Path(str(uploaded.name)).name or 'uploaded_file'


def inferred_brand_name(file_name):
    return Path(str(file_name)).stem or 'uploaded_file'


def auth_session_is_valid(authenticated, authenticated_at, now, timeout_seconds=AUTH_SESSION_TIMEOUT_SECONDS):
    if not authenticated:
        return False
    try:
        authenticated_at = float(authenticated_at)
    except (TypeError, ValueError):
        return False
    return 0 <= float(now) - authenticated_at <= timeout_seconds


def lockout_remaining_seconds(locked_until, now):
    try:
        remaining = float(locked_until) - float(now)
    except (TypeError, ValueError):
        return 0
    return max(0, int(math.ceil(remaining)))


def next_login_failure_state(failed_attempts, now, max_attempts=AUTH_MAX_FAILED_ATTEMPTS, lockout_seconds=AUTH_LOCKOUT_SECONDS):
    try:
        failures = int(failed_attempts)
    except (TypeError, ValueError):
        failures = 0
    failures += 1
    locked_until = float(now) + lockout_seconds if failures >= max_attempts else 0
    return failures, locked_until


def upload_size(uploaded):
    size = getattr(uploaded, 'size', None)
    if size is not None:
        return int(size)
    position = uploaded.tell()
    uploaded.seek(0, 2)
    size = uploaded.tell()
    uploaded.seek(position)
    return int(size)


def validate_uploaded_file(uploaded):
    file_name = uploaded_display_name(uploaded)
    suffix = Path(file_name).suffix.lower()
    if suffix == '.xlsm':
        raise ValueError('Macro-enabled Excel files (.xlsm) are blocked. Save the workbook as .xlsx or .csv and upload again.')
    if suffix not in ALLOWED_UPLOAD_SUFFIXES:
        allowed = ', '.join(ALLOWED_UPLOAD_SUFFIXES)
        raise ValueError(f'Unsupported file type "{suffix or "unknown"}". Allowed types: {allowed}.')
    size = upload_size(uploaded)
    if size > MAX_UPLOAD_BYTES:
        size_mb = size / (1024 * 1024)
        raise ValueError(f'{file_name} is {size_mb:.1f} MB. The upload limit is {MAX_UPLOAD_SIZE_MB} MB.')
    uploaded.seek(0)


def friendly_upload_error(error):
    message = str(error)
    hints = [
        f'Allowed files: {", ".join(ALLOWED_UPLOAD_SUFFIXES)}; .xlsm is blocked.',
        f'Limits: {MAX_UPLOAD_SIZE_MB} MB, {MAX_UPLOAD_ROWS:,} rows, {MAX_UPLOAD_COLUMNS:,} columns.',
        'If the workbook has title rows, open Upload interpretation and select the real header row.',
        'Password-protected or corrupted workbooks cannot be read.',
    ]
    return message + '\n\nCheck: ' + ' '.join(hints)


def list_excel_sheets(uploaded):
    name = uploaded.name.lower()
    if not name.endswith(('.xlsx', '.xls')):
        return []
    uploaded.seek(0)
    try:
        return pd.ExcelFile(uploaded).sheet_names
    finally:
        uploaded.seek(0)


def clean_column_label(label, index):
    if pd.isna(label):
        return f'Column {index + 1}'
    text = re.sub(r'\s+', ' ', str(label).strip())
    if not text or text.lower().startswith('unnamed:'):
        return f'Column {index + 1}'
    return text


def make_unique_columns(columns):
    clean = []
    seen = {}
    for index, column in enumerate(columns):
        base = clean_column_label(column, index)
        count = seen.get(base, 0)
        seen[base] = count + 1
        clean.append(base if count == 0 else f'{base} ({count + 1})')
    return clean


def clean_table(df):
    df = df.copy()
    df.columns = make_unique_columns(df.columns)
    df = df.dropna(how='all')
    return df.reset_index(drop=True)


def enforce_table_limits(df, file_name):
    if len(df) > MAX_UPLOAD_ROWS:
        raise ValueError(f'{file_name} has more than {MAX_UPLOAD_ROWS:,} rows. Split the file or reduce it before uploading.')
    if len(df.columns) > MAX_UPLOAD_COLUMNS:
        raise ValueError(f'{file_name} has {len(df.columns):,} columns. The limit is {MAX_UPLOAD_COLUMNS:,} columns.')


def read_preview_table(uploaded, sheet_name=None, nrows=25):
    name = uploaded.name.lower()
    uploaded.seek(0)
    if name.endswith('.csv'):
        preview = pd.read_csv(uploaded, header=None, nrows=nrows)
    elif name.endswith(('.xlsx', '.xls')):
        preview = pd.read_excel(uploaded, sheet_name=sheet_name or 0, header=None, nrows=nrows)
    else:
        raise ValueError('Unsupported file type')
    uploaded.seek(0)
    preview.columns = [f'Column {i + 1}' for i in range(len(preview.columns))]
    return preview


def infer_header_row(preview, expected_fields):
    best_row = 0
    best_score = -1
    for row_number, row in preview.head(20).iterrows():
        candidate_columns = [clean_column_label(value, i) for i, value in enumerate(row.tolist())]
        non_empty = [column for column in candidate_columns if not column.startswith('Column ')]
        if not non_empty:
            continue
        detected = sum(1 for logical in expected_fields if detect_column(candidate_columns, logical))
        score = detected * 10 + min(len(non_empty), 10)
        if score > best_score:
            best_row = int(row_number)
            best_score = score
    return best_row


def read_tabular(uploaded, sheet_name=None, header_row=0):
    name = uploaded.name.lower()
    file_name = uploaded_display_name(uploaded)
    uploaded.seek(0)
    if name.endswith('.csv'):
        df = pd.read_csv(uploaded, header=header_row, nrows=MAX_UPLOAD_ROWS + 1)
    elif name.endswith(('.xlsx', '.xls')):
        df = pd.read_excel(uploaded, sheet_name=sheet_name or 0, header=header_row, nrows=MAX_UPLOAD_ROWS + 1)
    else:
        raise ValueError('Unsupported file type')
    uploaded.seek(0)
    df = clean_table(df)
    enforce_table_limits(df, file_name)
    df.attrs['source_data_start_row'] = header_row + 2
    return df


def make_key(medium, channel, day, programme):
    return (
        medium.map(normalize_text) + '|' +
        channel.map(normalize_text) + '|' +
        day.map(normalize_day) + '|' +
        programme.map(normalize_text)
    )


def normalized_series(df, column, normalizer=normalize_text):
    if column not in df.columns:
        return pd.Series([''] * len(df), index=df.index)
    return df[column].map(normalizer)


def safe_col(df, col, default=''):
    if col and col != '-- none --':
        return df[col]
    return pd.Series([default] * len(df), index=df.index)


def non_empty_mask(series):
    text = series.astype('string')
    return text.notna() & text.str.strip().ne('') & text.str.strip().str.lower().ne('nan')


def missing_match_field_mask(df, fields):
    mask = pd.Series(False, index=df.index)
    for field in fields:
        mask = mask | ~non_empty_mask(df[field])
    return mask


def issue_frame(df, mask, issue, source_file=None):
    if not mask.any():
        return pd.DataFrame()
    issues = df.loc[mask].copy()
    if 'Input Row' not in issues.columns:
        issues['Input Row'] = issues.index + 2
    if source_file and 'Source File' not in issues.columns:
        issues['Source File'] = source_file
    issues['Issue'] = issue
    return issues


def input_row_numbers(df):
    return df.index + int(df.attrs.get('source_data_start_row', 2))


def excel_safe_value(value):
    if isinstance(value, str) and value.startswith(EXCEL_FORMULA_PREFIXES):
        return "'" + value
    return value


def excel_safe_df(df):
    safe = df.copy()
    for col in safe.select_dtypes(include=['object', 'string']).columns:
        safe[col] = safe[col].map(excel_safe_value)
    return safe


def display_safe_df(df):
    return df.astype('string').fillna('')


def sample_values(series, limit=3):
    filled = series.astype('string')
    filled = filled[filled.notna() & filled.str.strip().ne('') & filled.str.strip().str.lower().ne('nan')]
    samples = []
    seen = set()
    for value in filled.astype(str):
        cleaned = re.sub(r'\s+', ' ', value.strip())
        if not cleaned or cleaned in seen:
            continue
        samples.append(cleaned)
        seen.add(cleaned)
        if len(samples) == limit:
            break
    return ', '.join(samples)


def profile_mapping(df, mapping, fields, numeric_fields=()):
    total_rows = len(df)
    numeric_set = set(numeric_fields)
    rows = []
    for logical in fields:
        mapped_column = mapping.get(logical, '-- none --')
        mapped = bool(mapped_column and mapped_column != '-- none --' and mapped_column in df.columns)
        row = {
            'Field': logical,
            'Mapped Column': mapped_column if mapped else '-- none --',
            'Mapped': mapped,
            'Filled Rows': 0,
            'Fill Rate': 0.0,
            'Numeric Rows': pd.NA,
            'Numeric Fill Rate': pd.NA,
            'Sample Values': '',
        }
        if mapped:
            series = df[mapped_column]
            filled_mask = non_empty_mask(series)
            filled_rows = int(filled_mask.sum())
            row['Filled Rows'] = filled_rows
            row['Fill Rate'] = filled_rows / total_rows if total_rows else 0.0
            row['Sample Values'] = sample_values(series)
            if logical in numeric_set:
                numeric_values = pd.to_numeric(series, errors='coerce')
                numeric_rows = int((filled_mask & numeric_values.notna()).sum())
                row['Numeric Rows'] = numeric_rows
                row['Numeric Fill Rate'] = numeric_rows / filled_rows if filled_rows else 0.0
        rows.append(row)
    return pd.DataFrame(rows)


def numeric_issue_fields_from_profile(profile, numeric_fields):
    if profile.empty:
        return []
    numeric_profile = profile.loc[
        profile['Field'].isin(numeric_fields) & profile['Mapped'].fillna(False)
    ].copy()
    if numeric_profile.empty:
        return []
    filled_rows = pd.to_numeric(numeric_profile['Filled Rows'], errors='coerce').fillna(0)
    numeric_rows = pd.to_numeric(numeric_profile['Numeric Rows'], errors='coerce')
    issue_mask = numeric_rows.notna() & filled_rows.gt(numeric_rows)
    return numeric_profile.loc[issue_mask, 'Field'].tolist()


def mapping_ready_rows(df, mapping, required_fields, numeric_fields=()):
    if df.empty:
        return 0
    numeric_set = set(numeric_fields)
    ready_mask = pd.Series(True, index=df.index)
    for logical in required_fields:
        mapped_column = mapping.get(logical, '-- none --')
        if not mapped_column or mapped_column == '-- none --' or mapped_column not in df.columns:
            return 0
        series = df[mapped_column]
        field_mask = non_empty_mask(series)
        if logical in numeric_set:
            field_mask = field_mask & pd.to_numeric(series, errors='coerce').notna()
        ready_mask = ready_mask & field_mask
    return int(ready_mask.sum())


def mapped_field_preview(df, mapping, fields, defaults=None, labels=None, numeric_fields=(), max_rows=10):
    defaults = defaults or {}
    labels = labels or {}
    numeric_set = set(numeric_fields)
    preview = pd.DataFrame(index=df.index)
    preview['Input Row'] = input_row_numbers(df)
    for logical in fields:
        mapped_column = mapping.get(logical, '-- none --')
        if mapped_column and mapped_column != '-- none --' and mapped_column in df.columns:
            values = df[mapped_column]
        else:
            values = pd.Series([defaults.get(logical, '')] * len(df), index=df.index)
        if logical in numeric_set:
            values = pd.to_numeric(values, errors='coerce')
        preview[labels.get(logical, logical)] = values
    return preview.head(max_rows).reset_index(drop=True)


def build_run_summary(
    media,
    summary_df,
    category_grps,
    ratings=None,
    invalid_ratings=None,
    report_issues=None,
    dup_keys=None,
    suspicious_mediums=None,
    generated_at='',
    row_label='Report rows',
    matched_label='Matched rows',
    unmatched_label='Unmatched rows',
    progress_label='Match rate',
):
    ratings = ratings if ratings is not None else pd.DataFrame()
    invalid_ratings = invalid_ratings if invalid_ratings is not None else pd.DataFrame()
    report_issues = report_issues if report_issues is not None else pd.DataFrame()
    dup_keys = dup_keys if dup_keys is not None else pd.DataFrame()
    suspicious_mediums = suspicious_mediums or []

    total_rows = len(media)
    unmatched_rows = int(media['Match Status'].eq('NO RATING MATCH').sum()) if 'Match Status' in media.columns else 0
    matched_rows = total_rows - unmatched_rows
    coverage = matched_rows / total_rows if total_rows else 0
    total_spots = float(media['Spots'].sum()) if 'Spots' in media.columns and total_rows else 0
    total_tv_grps = float(summary_df['TV GRPs'].sum()) if 'TV GRPs' in summary_df.columns and len(summary_df) else 0
    total_radio_grps = float(summary_df['Radio GRPs'].sum()) if 'Radio GRPs' in summary_df.columns and len(summary_df) else 0

    rows = [
        ('Generated At', generated_at, 'Local app time when the workbook was created.'),
        ('Brands', summary_df['Brand'].nunique() if 'Brand' in summary_df.columns else 0, 'Unique brands included in the summary.'),
        (row_label, total_rows, 'Rows included in the calculation output.'),
        (matched_label, matched_rows, 'Rows with enough information to calculate GRPs.'),
        (unmatched_label, unmatched_rows, 'Rows that need review before final reporting.'),
        (progress_label, coverage, 'Calculated as matched rows divided by included rows.'),
        ('Total Spots', total_spots, 'Sum of included spot counts.'),
        ('TV GRPs', total_tv_grps, 'Total GRPs where Medium resolves to TV.'),
        ('Radio GRPs', total_radio_grps, 'Total GRPs where Medium resolves to Radio.'),
        ('Total Category GRPs', float(category_grps), 'Sum of all brand Total GRPs.'),
        ('Ratings Rows', len(ratings), 'Valid rating rows used for matching, when applicable.'),
        ('Duplicate Rating Keys', len(dup_keys), 'Rating match keys that appeared more than once.'),
        ('Invalid Rating Rows', len(invalid_ratings), 'Rating rows excluded before matching.'),
        ('Report Input Issues', len(report_issues), 'Report rows excluded before calculation.'),
        ('Suspicious Medium Values', len(suspicious_mediums), 'Medium values outside TV/Radio aliases.'),
    ]
    return pd.DataFrame(rows, columns=['Metric', 'Value', 'Notes'])


def build_validation_summary(media, invalid_ratings=None, report_issues=None, dup_keys=None, suspicious_mediums=None):
    invalid_ratings = invalid_ratings if invalid_ratings is not None else pd.DataFrame()
    report_issues = report_issues if report_issues is not None else pd.DataFrame()
    dup_keys = dup_keys if dup_keys is not None else pd.DataFrame()
    suspicious_mediums = suspicious_mediums or []
    unmatched_rows = int(media['Match Status'].eq('NO RATING MATCH').sum()) if 'Match Status' in media.columns else 0

    rows = [
        (
            'Duplicate rating keys',
            len(dup_keys),
            'Review' if len(dup_keys) else 'OK',
            'Duplicate keys are averaged before matching.',
        ),
        (
            'Invalid ratings',
            len(invalid_ratings),
            'Review' if len(invalid_ratings) else 'OK',
            'Rows with missing fields or non-numeric/out-of-range ratings are excluded.',
        ),
        (
            'Report input issues',
            len(report_issues),
            'Review' if len(report_issues) else 'OK',
            'Rows with missing fields, invalid spots, or invalid GRP values are excluded.',
        ),
        (
            'Unmatched rows',
            unmatched_rows,
            'Review' if unmatched_rows else 'OK',
            'Rows without a rating match contribute no GRPs until fixed.',
        ),
        (
            'Suspicious medium values',
            len(suspicious_mediums),
            'Review' if len(suspicious_mediums) else 'OK',
            'Medium values that do not resolve to TV or Radio.',
        ),
    ]
    return pd.DataFrame(rows, columns=['Area', 'Count', 'Status', 'Notes'])


def build_unmatched_suggestions(media, ratings, max_suggestions_per_row=3, min_score=0.55):
    if ratings is None or len(ratings) == 0 or len(media) == 0:
        return pd.DataFrame(columns=SUGGESTION_COLUMNS)
    if 'Match Status' not in media.columns:
        return pd.DataFrame(columns=SUGGESTION_COLUMNS)

    unmatched = media.loc[media['Match Status'].eq('NO RATING MATCH')].copy()
    if unmatched.empty:
        return pd.DataFrame(columns=SUGGESTION_COLUMNS)

    ratings_index = ratings.copy()
    ratings_index['_MediumNorm'] = normalized_series(ratings_index, 'Medium')
    ratings_index['_ChannelNorm'] = normalized_series(ratings_index, 'Channel / Station')
    ratings_index['_DayNorm'] = normalized_series(ratings_index, 'Day', normalize_day)
    ratings_index['_ProgrammeNorm'] = normalized_series(ratings_index, 'Programme / Time Band')

    suggestions = []
    for media_index, row in unmatched.iterrows():
        medium_norm = normalize_text(row.get('Medium', ''))
        channel_norm = normalize_text(row.get('Channel / Station', ''))
        day_norm = normalize_day(row.get('Day', ''))
        programme = row.get('Programme / Time Band', '')

        candidate_sets = [
            (
                'Same medium, channel, and day',
                ratings_index[
                    ratings_index['_MediumNorm'].eq(medium_norm)
                    & ratings_index['_ChannelNorm'].eq(channel_norm)
                    & ratings_index['_DayNorm'].eq(day_norm)
                ],
            ),
            (
                'Same medium and channel',
                ratings_index[
                    ratings_index['_MediumNorm'].eq(medium_norm)
                    & ratings_index['_ChannelNorm'].eq(channel_norm)
                ],
            ),
            (
                'Same medium and day',
                ratings_index[
                    ratings_index['_MediumNorm'].eq(medium_norm)
                    & ratings_index['_DayNorm'].eq(day_norm)
                ],
            ),
        ]

        candidate_rows = pd.DataFrame()
        basis = ''
        for candidate_basis, candidates in candidate_sets:
            if not candidates.empty:
                candidate_rows = candidates.copy()
                basis = candidate_basis
                break
        if candidate_rows.empty:
            continue

        candidate_rows['_Similarity'] = candidate_rows['Programme / Time Band'].map(
            lambda candidate: text_similarity(programme, candidate)
        )
        candidate_rows = candidate_rows.loc[candidate_rows['_Similarity'].ge(min_score)].copy()
        if candidate_rows.empty:
            continue
        candidate_rows = candidate_rows.sort_values(['_Similarity', 'Rating (%)'], ascending=[False, False])
        candidate_rows = candidate_rows.drop_duplicates(
            subset=['Channel / Station', 'Day', 'Programme / Time Band', 'Rating (%)']
        ).head(max_suggestions_per_row)

        for _, candidate in candidate_rows.iterrows():
            score = round(float(candidate['_Similarity']), 3)
            suggestions.append({
                'Brand': row.get('Brand', ''),
                'Source File': row.get('Source File', ''),
                'Input Medium': row.get('Medium', ''),
                'Input Channel / Station': row.get('Channel / Station', ''),
                'Input Day': row.get('Day', ''),
                'Input Programme / Time Band': programme,
                'Suggested Channel / Station': candidate.get('Channel / Station', ''),
                'Suggested Day': candidate.get('Day', ''),
                'Suggested Programme / Time Band': candidate.get('Programme / Time Band', ''),
                'Suggested Rating (%)': candidate.get('Rating (%)', pd.NA),
                'Similarity Score': score,
                'Confidence': suggestion_confidence(score),
                'Suggestion Basis': basis,
                'Input Match Key': row.get('Match Key', ''),
                'Suggested Match Key': candidate.get('Match Key', ''),
            })

    return pd.DataFrame(suggestions, columns=SUGGESTION_COLUMNS)


def build_ratings_lookup(ratings_raw, mapping, default_medium='TV'):
    rating_values = pd.to_numeric(safe_col(ratings_raw, mapping['rating']), errors='coerce')
    ratings_all = pd.DataFrame({
        'Medium': safe_col(ratings_raw, mapping['medium'], default_medium),
        'Channel / Station': safe_col(ratings_raw, mapping['channel']),
        'Day': safe_col(ratings_raw, mapping['day']),
        'Programme / Time Band': safe_col(ratings_raw, mapping['programme']),
        'Rating (%)': rating_values,
        'Source / Period': safe_col(ratings_raw, mapping.get('source')),
    })
    ratings_all['Input Row'] = input_row_numbers(ratings_raw)
    bad_rating_mask = ratings_all['Rating (%)'].isna() | ratings_all['Rating (%)'].lt(0) | ratings_all['Rating (%)'].gt(100)
    missing_fields_mask = missing_match_field_mask(ratings_all, ['Medium', 'Channel / Station', 'Day', 'Programme / Time Band'])
    invalid_mask = bad_rating_mask | missing_fields_mask
    invalid_ratings = pd.concat([
        issue_frame(ratings_all, bad_rating_mask, 'Invalid or out-of-range rating'),
        issue_frame(ratings_all, missing_fields_mask, 'Missing rating match field'),
    ], ignore_index=True)
    ratings = ratings_all.loc[~invalid_mask].drop(columns=['Input Row']).copy()
    if not ratings.empty:
        ratings['Match Key'] = make_key(ratings['Medium'], ratings['Channel / Station'], ratings['Day'], ratings['Programme / Time Band'])
    key_counts = ratings.groupby('Match Key').size().rename('Rows').reset_index() if not ratings.empty else pd.DataFrame(columns=['Match Key', 'Rows'])
    dup_keys = key_counts[key_counts['Rows'] > 1].copy()
    ratings_lookup = ratings.groupby('Match Key', as_index=False)['Rating (%)'].mean() if not ratings.empty else pd.DataFrame(columns=['Match Key', 'Rating (%)'])
    return ratings, invalid_ratings, dup_keys, ratings_lookup


def build_brand_report(raw, mapping, file_name, default_medium='TV'):
    inferred_brand = inferred_brand_name(file_name)
    brand_series = safe_col(raw, mapping['brand'], inferred_brand).fillna('').astype(str).str.strip()
    brand_series = brand_series.mask(brand_series.eq(''), inferred_brand)

    day_series = safe_col(raw, mapping['day'])
    if mapping['date'] != '-- none --':
        derived = derive_day(safe_col(raw, mapping['date']))
        day_series = day_series.where(non_empty_mask(day_series), derived)

    spots_values = pd.to_numeric(safe_col(raw, mapping['spots'], 1), errors='coerce')
    spot_issue_mask = spots_values.isna() | spots_values.le(0)
    report = pd.DataFrame({
        'Brand': brand_series,
        'Medium': safe_col(raw, mapping['medium'], default_medium),
        'Date': safe_col(raw, mapping['date']),
        'Day': day_series,
        'Channel / Station': safe_col(raw, mapping['channel']),
        'Programme / Time Band': safe_col(raw, mapping['programme']),
        'Spots': spots_values.fillna(0),
        'Source File': file_name,
    })
    report['Input Row'] = input_row_numbers(raw)
    missing_fields_mask = missing_match_field_mask(report, ['Medium', 'Channel / Station', 'Day', 'Programme / Time Band'])
    issues = pd.concat([
        issue_frame(report, spot_issue_mask, 'Invalid, zero, or negative spots', file_name),
        issue_frame(report, missing_fields_mask, 'Missing report match field', file_name),
    ], ignore_index=True)
    valid_mask = ~(spot_issue_mask | missing_fields_mask)
    report = report.loc[valid_mask].drop(columns=['Input Row']).copy()
    if not report.empty:
        report['Match Key'] = make_key(report['Medium'], report['Channel / Station'], report['Day'], report['Programme / Time Band'])
    return report, issues


def build_composite_report(raw, mapping, file_name, default_medium='TV'):
    inferred_brand = inferred_brand_name(file_name)
    brand_series = safe_col(raw, mapping['brand'], inferred_brand).fillna('').astype(str).str.strip()
    brand_series = brand_series.mask(brand_series.eq(''), inferred_brand)

    day_series = safe_col(raw, mapping['day'])
    if mapping['date'] != '-- none --':
        derived = derive_day(safe_col(raw, mapping['date']))
        day_series = day_series.where(non_empty_mask(day_series), derived)

    spots_values = pd.to_numeric(safe_col(raw, mapping['spots'], 1), errors='coerce')
    rating_values = pd.to_numeric(safe_col(raw, mapping['rating'], pd.NA), errors='coerce')
    uploaded_grp_values = pd.to_numeric(safe_col(raw, mapping['grp'], pd.NA), errors='coerce')
    direct_grp_mask = uploaded_grp_values.notna()
    calculated_grp_values = spots_values * rating_values
    grp_values = uploaded_grp_values.where(direct_grp_mask, calculated_grp_values)

    report = pd.DataFrame({
        'Brand': brand_series,
        'Medium': safe_col(raw, mapping['medium'], default_medium),
        'Date': safe_col(raw, mapping['date']),
        'Day': day_series,
        'Channel / Station': safe_col(raw, mapping['channel']),
        'Programme / Time Band': safe_col(raw, mapping['programme']),
        'Spots': spots_values.fillna(0),
        'Matched Rating (%)': rating_values,
        'GRP': grp_values,
        'GRP Source': direct_grp_mask.map({True: 'Uploaded GRP', False: 'Spots x Rating'}),
        'Match Status': direct_grp_mask.map({True: 'CALCULATED FROM UPLOADED GRP', False: 'CALCULATED FROM RATING'}),
        'Source File': file_name,
    })
    report['Input Row'] = input_row_numbers(raw)
    report['Match Key'] = make_key(report['Medium'], report['Channel / Station'], report['Day'], report['Programme / Time Band'])

    missing_fields_mask = missing_match_field_mask(report, ['Medium', 'Channel / Station', 'Day', 'Programme / Time Band'])
    bad_spots_mask = spots_values.isna() | spots_values.le(0)
    bad_rating_mask = ~direct_grp_mask & (rating_values.isna() | rating_values.lt(0) | rating_values.gt(100))
    bad_uploaded_grp_mask = direct_grp_mask & uploaded_grp_values.lt(0)
    bad_grp_mask = grp_values.isna() | grp_values.lt(0) | bad_rating_mask | bad_uploaded_grp_mask
    issues = pd.concat([
        issue_frame(report, missing_fields_mask, 'Missing composite match field', file_name),
        issue_frame(report, bad_spots_mask, 'Invalid, zero, or negative spots', file_name),
        issue_frame(report, bad_grp_mask, 'Invalid rating or GRP calculation', file_name),
    ], ignore_index=True)
    valid_mask = ~(missing_fields_mask | bad_spots_mask | bad_grp_mask)
    report = report.loc[valid_mask].drop(columns=['Input Row']).copy()
    return report, issues


def match_reports_to_ratings(report_frames, ratings_lookup):
    media = pd.concat(report_frames, ignore_index=True)
    media = media.merge(ratings_lookup, how='left', on='Match Key')
    media.rename(columns={'Rating (%)': 'Matched Rating (%)'}, inplace=True)
    media['GRP'] = media['Spots'] * media['Matched Rating (%)']
    media['Match Status'] = media['Matched Rating (%)'].notna().map({True: 'MATCHED', False: 'NO RATING MATCH'})
    media['_MediumCanon'] = media['Medium'].map(normalize_medium_type)
    return media


def summarize_media(media):
    media = media.copy()
    if '_MediumCanon' not in media.columns:
        media['_MediumCanon'] = media['Medium'].map(normalize_medium_type)

    brand_rows = []
    for brand, g in media.groupby('Brand', dropna=False):
        tv = g.loc[g['_MediumCanon'].eq('TV'), 'GRP'].sum(min_count=1)
        radio = g.loc[g['_MediumCanon'].eq('RADIO'), 'GRP'].sum(min_count=1)
        tv = 0 if pd.isna(tv) else float(tv)
        radio = 0 if pd.isna(radio) else float(radio)
        total = tv + radio
        brand_rows.append({
            'Brand': brand,
            'TV GRPs': tv,
            'Radio GRPs': radio,
            'Total GRPs': total,
            'Total Spots': g['Spots'].sum(),
            'Unmatched Rows': int(g['Match Status'].eq('NO RATING MATCH').sum()),
        })
    summary_df = pd.DataFrame(brand_rows)
    category_grps = summary_df['Total GRPs'].sum() if len(summary_df) else 0
    summary_df['GRP SOV'] = summary_df['Total GRPs'] / category_grps if category_grps else 0
    summary_df = summary_df.sort_values('Total GRPs', ascending=False)
    suspicious_mediums = sorted(media.loc[media['_MediumCanon'].isin(['OTHER', 'MISSING']), 'Medium'].astype(str).unique())
    return summary_df, category_grps, suspicious_mediums
