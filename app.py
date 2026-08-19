import io
import hmac
import os
import re
import time
from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st

import grp_calculator as calc

st.set_page_config(page_title='Mediapulse', page_icon=':bar_chart:', layout='wide')

FIELD_LABELS = {
    'brand': 'Brand',
    'medium': 'Medium',
    'date': 'Date',
    'day': 'Day',
    'channel': 'Channel / Station',
    'programme': 'Programme / Time Band',
    'spots': 'Spots',
    'rating': 'Rating (%)',
    'grp': 'GRP',
    'source': 'Source / Period',
}


def configured_password():
    env_password = os.environ.get('GRP_APP_PASSWORD', '').strip()
    if env_password:
        return env_password
    try:
        secret_password = st.secrets.get('APP_PASSWORD', '')
    except Exception:
        secret_password = ''
    return str(secret_password).strip()


def require_password_gate():
    password = configured_password()
    if not password:
        st.warning('Password gate is disabled. Set GRP_APP_PASSWORD or Streamlit secret APP_PASSWORD before shared deployment.')
        return

    now = time.time()
    if calc.auth_session_is_valid(
        st.session_state.get('authenticated'),
        st.session_state.get('authenticated_at'),
        now,
    ):
        with st.sidebar:
            st.caption('Access: authenticated')
            if st.button('Log out'):
                clear_auth_state()
                st.rerun()
        return
    if st.session_state.get('authenticated'):
        clear_auth_state()
        st.warning('Your session expired. Enter the app password again.')

    st.title('Mediapulse')
    st.caption('Enter the app password to continue.')
    remaining_lockout = calc.lockout_remaining_seconds(st.session_state.get('locked_until'), now)
    if remaining_lockout:
        st.error(f'Too many incorrect attempts. Try again in {remaining_lockout} seconds.')
        st.stop()
    if st.session_state.get('locked_until'):
        st.session_state['failed_login_attempts'] = 0
        st.session_state['locked_until'] = 0

    with st.form('password_gate'):
        submitted_password = st.text_input('Password', type='password')
        submitted = st.form_submit_button('Continue')
    if submitted:
        if hmac.compare_digest(submitted_password, password):
            st.session_state['authenticated'] = True
            st.session_state['authenticated_at'] = now
            st.session_state['failed_login_attempts'] = 0
            st.session_state['locked_until'] = 0
            st.rerun()
        failures, locked_until = calc.next_login_failure_state(st.session_state.get('failed_login_attempts'), now)
        st.session_state['failed_login_attempts'] = failures
        st.session_state['locked_until'] = locked_until
        if locked_until:
            st.error(f'Too many incorrect attempts. Try again in {calc.lockout_remaining_seconds(locked_until, now)} seconds.')
        else:
            attempts_left = calc.AUTH_MAX_FAILED_ATTEMPTS - failures
            st.error(f'Incorrect password. {attempts_left} attempts remaining.')
    st.stop()


def clear_auth_state():
    for key in ['authenticated', 'authenticated_at', 'failed_login_attempts', 'locked_until']:
        st.session_state.pop(key, None)


def sheet_selector(uploaded, key):
    sheets = calc.list_excel_sheets(uploaded)
    if not sheets:
        return None
    if len(sheets) == 1:
        st.caption(f'Using sheet: {sheets[0]}')
        return sheets[0]
    return st.selectbox('Worksheet', sheets, key=key)


def row_summary(row):
    values = []
    for value in row.tolist():
        if pd.isna(value):
            continue
        text = re.sub(r'\s+', ' ', str(value).strip())
        if text:
            values.append(text)
        if len(values) == 4:
            break
    return ' | '.join(values) or 'blank row'


def header_row_selector(preview, suggested, key):
    max_rows = min(len(preview), 20)
    choices = list(range(max_rows)) or [0]
    if suggested not in choices:
        suggested = 0
    return st.selectbox(
        'Header row',
        choices,
        index=choices.index(suggested),
        format_func=lambda row: f'Row {row + 1}: {row_summary(preview.iloc[row])}',
        key=key,
        help='Choose the row that contains the column names. Data should start below this row.',
    )


def load_tabular_with_controls(uploaded, key, expected_fields, expanded=False):
    calc.validate_uploaded_file(uploaded)
    sheet_name = sheet_selector(uploaded, f'{key}_sheet')
    preview = calc.read_preview_table(uploaded, sheet_name)
    if preview.empty:
        raise ValueError('The uploaded file does not contain any readable rows.')
    suggested_header = calc.infer_header_row(preview, expected_fields)
    with st.expander('Upload interpretation', expanded=expanded or suggested_header > 0):
        header_row = header_row_selector(preview, suggested_header, f'{key}_header_row')
        st.caption('Raw file preview before parsing')
        st.dataframe(calc.display_safe_df(preview.head(12)), width='stretch', height=240)
    df = calc.read_tabular(uploaded, sheet_name, header_row)
    st.caption(f'Parsed {len(df):,} rows and {len(df.columns):,} columns using row {header_row + 1} as headers.')
    with st.expander('Parsed data preview'):
        st.dataframe(calc.display_safe_df(df.head(20)), width='stretch', height=240)
    return df


def field_label(logical):
    return FIELD_LABELS.get(logical, logical.replace('_', ' ').title())


def format_rate(value):
    if pd.isna(value):
        return ''
    return f'{float(value):.0%}'


def mapping_ui(df, prefix, required, optional=()):
    options = ['-- none --'] + list(df.columns)
    mapping = {}
    cols = st.columns(min(4, max(1, len(required) + len(optional))))
    fields = list(required) + list(optional)
    for i, logical in enumerate(fields):
        detected = calc.detect_column(df.columns, logical)
        default_idx = options.index(detected) if detected in options else 0
        with cols[i % len(cols)]:
            label = field_label(logical)
            if logical in required:
                label = f'{label} *'
            mapping[logical] = st.selectbox(
                label,
                options,
                index=default_idx,
                key=f'{prefix}_{logical}',
            )
    return mapping


def render_mapping_review(
    df,
    mapping,
    key,
    required,
    optional=(),
    numeric_fields=(),
    defaults=None,
    expanded=False,
):
    fields = list(required) + list(optional)
    defaults = defaults or {}
    missing_required = [field for field in required if mapping.get(field) == '-- none --']
    ready_rows = calc.mapping_ready_rows(df, mapping, required, numeric_fields=numeric_fields)
    mapped_required = len(required) - len(missing_required)
    labels = {field: field_label(field) for field in fields}
    review_expanded = expanded or bool(missing_required) or ready_rows < len(df)

    with st.expander('Mapping review', expanded=review_expanded):
        metric_cols = st.columns(3)
        metric_cols[0].metric('Required mapped', f'{mapped_required}/{len(required)}')
        metric_cols[1].metric('Ready rows', f'{ready_rows:,}/{len(df):,}')
        metric_cols[2].metric('Parsed columns', f'{len(df.columns):,}')

        if missing_required:
            st.warning('Map required fields before calculating: ' + ', '.join(field_label(field) for field in missing_required))

        if defaults:
            default_notes = [f'{field_label(field)} = {value}' for field, value in defaults.items() if value]
            if default_notes:
                st.caption('Defaults applied when a field is not mapped: ' + '; '.join(default_notes))

        profile = calc.profile_mapping(df, mapping, fields, numeric_fields=numeric_fields)
        if len(profile):
            profile_view = profile.copy()
            profile_view['Field'] = profile_view['Field'].map(field_label)
            profile_view['Mapped'] = profile_view['Mapped'].map({True: 'Yes', False: 'No'})
            profile_view['Fill Rate'] = profile_view['Fill Rate'].map(format_rate)
            profile_view['Numeric Fill Rate'] = profile_view['Numeric Fill Rate'].map(format_rate)
            st.dataframe(profile_view, width='stretch', hide_index=True)

            numeric_issues = calc.numeric_issue_fields_from_profile(profile, numeric_fields)
            if numeric_issues:
                issue_names = ', '.join(field_label(field) for field in numeric_issues)
                st.warning(f'Some mapped numeric values could not be read as numbers: {issue_names}.')

        preview = calc.mapped_field_preview(
            df,
            mapping,
            fields,
            defaults=defaults,
            labels=labels,
            numeric_fields=numeric_fields,
        )
        st.caption('Interpreted row preview')
        st.dataframe(calc.display_safe_df(preview), width='stretch', height=260)


def default_medium_selector(mapping, key):
    if mapping.get('medium') != '-- none --':
        return ''
    return st.selectbox(
        'Default Medium',
        ['TV', 'RADIO'],
        key=key,
        help='Used when the uploaded file has no Medium column.',
    )


def default_values_for_mapping(mapping, default_medium='', file_name=''):
    defaults = {}
    if mapping.get('medium') == '-- none --' and default_medium:
        defaults['medium'] = default_medium
    if mapping.get('brand') == '-- none --' and file_name:
        defaults['brand'] = calc.inferred_brand_name(file_name)
    return defaults


def make_template(kind):
    output = io.BytesIO()
    data, sheet_name = calc.template_dataframe(kind)
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        data.to_excel(writer, sheet_name=sheet_name, index=False)
    output.seek(0)
    return output.getvalue()


def render_validation_metrics(items):
    cols = st.columns(len(items))
    for col, (label, value, help_text) in zip(cols, items):
        col.metric(label, value, help=help_text)


def render_results(
    media,
    ratings=None,
    invalid_ratings=None,
    report_issues=None,
    dup_keys=None,
    result_header='3. Results',
    row_label='Report rows',
    matched_label='Matched rows',
    unmatched_label='Unmatched rows',
    input_issues_label='Input issues',
    input_issues_help='Rows excluded because required values were missing or invalid.',
    progress_label='Match rate',
    export_file_name='Mediapulse_GRP_SOV_results.xlsx',
):
    invalid_ratings = invalid_ratings if invalid_ratings is not None else pd.DataFrame()
    report_issues = report_issues if report_issues is not None else pd.DataFrame()
    dup_keys = dup_keys if dup_keys is not None else pd.DataFrame()

    media = media.copy()
    summary_df, category_grps, suspicious_mediums = calc.summarize_media(media)

    st.header(result_header)
    unmatched = int((media['Match Status'] == 'NO RATING MATCH').sum())
    total_rows = len(media)
    matched = total_rows - unmatched

    st.subheader('Validation Summary')
    render_validation_metrics([
        (row_label, f'{total_rows:,}', 'Rows included in the calculation.'),
        (matched_label, f'{matched:,}', 'Rows with enough data to calculate GRPs.'),
        (unmatched_label, f'{unmatched:,}', 'Rows that need review before final reporting.'),
        ('Duplicate keys', f'{len(dup_keys):,}', 'Rating match keys that appear more than once.'),
        (input_issues_label, f'{len(invalid_ratings) + len(report_issues):,}', input_issues_help),
        ('Suspicious media', f'{len(suspicious_mediums):,}', 'Medium values outside TV/Radio aliases.'),
    ])
    st.progress(matched / total_rows if total_rows else 0, text=f'{progress_label}: {(matched / total_rows * 100 if total_rows else 0):.1f}%')

    validation_summary = calc.build_validation_summary(
        media,
        invalid_ratings=invalid_ratings,
        report_issues=report_issues,
        dup_keys=dup_keys,
        suspicious_mediums=suspicious_mediums,
    )
    unmatched_suggestions = calc.build_unmatched_suggestions(media, ratings)

    audit_cols = [
        'Brand', 'Medium', 'Date', 'Day', 'Channel / Station', 'Programme / Time Band',
        'Spots', 'Matched Rating (%)', 'GRP', 'GRP Source', 'Match Status', 'Source File',
    ]
    audit_cols = [col for col in audit_cols if col in media.columns]

    summary_tab, audit_tab, validation_tab = st.tabs(['Summary', 'Spot Audit', 'Validation'])

    with summary_tab:
        st.subheader('Brand GRP & SOV Summary')
        chart_left, chart_right = st.columns(2)
        with chart_left:
            st.bar_chart(summary_df.set_index('Brand')[['TV GRPs', 'Radio GRPs']], width='stretch')
        with chart_right:
            sov_chart = alt.Chart(summary_df).mark_bar().encode(
                x=alt.X('GRP SOV:Q', axis=alt.Axis(format='%'), title='GRP SOV'),
                y=alt.Y('Brand:N', sort=alt.EncodingSortField(field='GRP SOV', order='descending'), title='Brand'),
                tooltip=['Brand', alt.Tooltip('Total GRPs:Q', format='.2f'), alt.Tooltip('GRP SOV:Q', format='.1%')],
            )
            st.altair_chart(sov_chart, width='stretch')
        st.dataframe(
            summary_df.style.format({
                'TV GRPs': '{:.2f}',
                'Radio GRPs': '{:.2f}',
                'Total GRPs': '{:.2f}',
                'GRP SOV': '{:.1%}',
                'Total Spots': '{:,.0f}',
            }),
            width='stretch',
        )
        st.markdown(f'**Total Category GRPs: {category_grps:.2f}**')
        st.caption('Calculation: each calculation row GRP = Spots x Matched Rating, or the uploaded GRP value when a composite report provides one. Brand Total GRPs = sum of all row GRPs for that brand. Category GRPs = sum of all brand Total GRPs.')

    with audit_tab:
        st.subheader('Spot-Level Calculation Audit')
        filter_cols = st.columns(5)
        with filter_cols[0]:
            brand_filter = st.multiselect('Brand', sorted(media['Brand'].astype(str).unique()))
        with filter_cols[1]:
            medium_filter = st.multiselect('Medium', sorted(media['Medium'].astype(str).unique()))
        with filter_cols[2]:
            status_filter = st.multiselect('Status', sorted(media['Match Status'].astype(str).unique()))
        with filter_cols[3]:
            source_filter = st.multiselect('Source file', sorted(media['Source File'].astype(str).unique()))
        with filter_cols[4]:
            search_text = st.text_input('Search audit rows')

        audit_view = media[audit_cols].copy()
        if brand_filter:
            audit_view = audit_view[audit_view['Brand'].astype(str).isin(brand_filter)]
        if medium_filter:
            audit_view = audit_view[audit_view['Medium'].astype(str).isin(medium_filter)]
        if status_filter:
            audit_view = audit_view[audit_view['Match Status'].astype(str).isin(status_filter)]
        if source_filter:
            audit_view = audit_view[audit_view['Source File'].astype(str).isin(source_filter)]
        if search_text.strip():
            needle = re.escape(search_text.strip())
            haystack = audit_view.astype(str).agg(' '.join, axis=1)
            audit_view = audit_view[haystack.str.contains(needle, case=False, na=False, regex=True)]

        st.caption(f'Showing {len(audit_view):,} of {len(media):,} rows.')
        st.dataframe(audit_view, width='stretch', height=420)

    with validation_tab:
        st.subheader('Rows Needing Review')
        st.dataframe(validation_summary, width='stretch', hide_index=True)
        if len(dup_keys):
            with st.expander('Duplicate rating keys', expanded=True):
                st.dataframe(dup_keys, width='stretch')
        if len(invalid_ratings):
            with st.expander('Invalid ratings dropped from lookup', expanded=True):
                st.dataframe(invalid_ratings, width='stretch')
        if len(report_issues):
            with st.expander('Report rows excluded from calculations', expanded=True):
                st.dataframe(report_issues, width='stretch')
        if suspicious_mediums:
            with st.expander('Suspicious medium values', expanded=True):
                st.dataframe(pd.DataFrame({'Medium': suspicious_mediums}), width='stretch')
        if unmatched:
            with st.expander('Unmatched rows', expanded=True):
                st.dataframe(media.loc[media['Match Status'].eq('NO RATING MATCH'), audit_cols], width='stretch')
        if len(unmatched_suggestions):
            with st.expander('Suggested rating matches for unmatched rows', expanded=True):
                st.dataframe(unmatched_suggestions, width='stretch')
        if not any([len(dup_keys), len(invalid_ratings), len(report_issues), len(suspicious_mediums), unmatched]):
            st.success('No validation issues found in this run.')

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        run_summary = calc.build_run_summary(
            media,
            summary_df,
            category_grps,
            ratings=ratings,
            invalid_ratings=invalid_ratings,
            report_issues=report_issues,
            dup_keys=dup_keys,
            suspicious_mediums=suspicious_mediums,
            generated_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            row_label=row_label,
            matched_label=matched_label,
            unmatched_label=unmatched_label,
            progress_label=progress_label,
        )
        calc.excel_safe_df(run_summary).to_excel(writer, sheet_name='Run Summary', index=False)
        calc.excel_safe_df(validation_summary).to_excel(writer, sheet_name='Validation Summary', index=False)
        calc.excel_safe_df(summary_df).to_excel(writer, sheet_name='Brand GRP Summary', index=False)
        if ratings is not None and len(ratings):
            calc.excel_safe_df(ratings).to_excel(writer, sheet_name='Ratings Used', index=False)
        export_cols = audit_cols + (['Match Key'] if 'Match Key' in media.columns else [])
        calc.excel_safe_df(media[export_cols]).to_excel(writer, sheet_name='Spot Level GRP', index=False)
        if len(invalid_ratings):
            calc.excel_safe_df(invalid_ratings).to_excel(writer, sheet_name='Invalid Ratings', index=False)
        if len(report_issues):
            calc.excel_safe_df(report_issues).to_excel(writer, sheet_name='Report Input Issues', index=False)
        if unmatched:
            calc.excel_safe_df(media.loc[media['Match Status'].eq('NO RATING MATCH'), export_cols]).to_excel(writer, sheet_name='Unmatched Rows', index=False)
        if len(unmatched_suggestions):
            calc.excel_safe_df(unmatched_suggestions).to_excel(writer, sheet_name='Unmatched Suggestions', index=False)
        if suspicious_mediums:
            calc.excel_safe_df(pd.DataFrame({'Medium': suspicious_mediums})).to_excel(writer, sheet_name='Suspicious Media', index=False)
    output.seek(0)
    st.download_button('Download Mediapulse Results (Excel)', data=output, file_name=export_file_name, mime=calc.TEMPLATE_MIME)


require_password_gate()

st.title('Mediapulse')
st.caption('Upload programme ratings and brand TV/Radio media reports. The app matches each airing to its rating, calculates GRPs, and summarizes brand SOV.')

with st.sidebar:
    st.header('How it works')
    st.markdown('Choose **Composite Report** for one workbook with spots and ratings/GRPs, or **Separate Ratings + Brand Reports** when ratings and activity are separate files.')
    st.info('GRP per row = Spots x Matched Rating. Brand SOV = Brand GRPs / Total Category GRPs.')
    st.header('Templates')
    st.download_button('Composite template', data=make_template('composite'), file_name='composite_report_template.xlsx', mime=calc.TEMPLATE_MIME)
    st.download_button('Ratings template', data=make_template('ratings'), file_name='ratings_template.xlsx', mime=calc.TEMPLATE_MIME)
    st.download_button('Brand report template', data=make_template('brand'), file_name='brand_report_template.xlsx', mime=calc.TEMPLATE_MIME)

workflow_mode = st.radio(
    'Workflow',
    ['Composite Report', 'Separate Ratings + Brand Reports'],
    horizontal=True,
    help='Use Composite Report when one workbook already contains spots and ratings/GRPs. Use Separate Ratings + Brand Reports when ratings and brand activity are separate files.',
)

workflow_help_cols = st.columns(2)
with workflow_help_cols[0]:
    st.caption('Composite example: a single weekly report with Channel, WD, Program, Spots, Rch %, and Grps.')
with workflow_help_cols[1]:
    st.caption('Separate example: one ratings file plus one or more brand activity files matched by channel, day, and programme.')

if workflow_mode == 'Composite Report':
    st.header('1. Composite Report')
    composite_files = st.file_uploader(
        'Upload one or more composite reports (.xlsx, .xls, or .csv)',
        type=calc.ALLOWED_UPLOAD_TYPES,
        accept_multiple_files=True,
        key='composite_reports',
    )
    if not composite_files:
        st.stop()

    composite_reports = []
    composite_issues = []
    for idx, uploaded in enumerate(composite_files):
        file_name = calc.uploaded_display_name(uploaded)
        st.subheader(f'Composite {idx + 1}: {file_name}')
        try:
            raw = load_tabular_with_controls(
                uploaded,
                f'composite_{idx}',
                ['brand', 'medium', 'date', 'day', 'channel', 'programme', 'spots', 'rating', 'grp'],
            )
        except Exception as e:
            st.error(f'Could not read {file_name}:\n\n{calc.friendly_upload_error(e)}')
            continue

        st.write('Map the composite report fields:')
        cmap = mapping_ui(
            raw,
            f'composite_{idx}',
            ['channel', 'programme', 'spots'],
            ['brand', 'medium', 'date', 'day', 'rating', 'grp'],
        )
        default_medium = default_medium_selector(cmap, f'composite_{idx}_default_medium')
        render_mapping_review(
            raw,
            cmap,
            f'composite_{idx}_review',
            ['channel', 'programme', 'spots'],
            ['brand', 'medium', 'date', 'day', 'rating', 'grp'],
            numeric_fields=['spots', 'rating', 'grp'],
            defaults=default_values_for_mapping(cmap, default_medium, file_name),
        )

        required_missing = [x for x in ['channel', 'programme', 'spots'] if cmap[x] == '-- none --']
        if required_missing:
            st.warning(f'Map required fields for {file_name}: {", ".join(required_missing)}')
            continue
        if cmap['date'] == '-- none --' and cmap['day'] == '-- none --':
            st.warning(f'Map either Date or Day for {file_name}.')
            continue
        if cmap['rating'] == '-- none --' and cmap['grp'] == '-- none --':
            st.warning(f'Map either Rating or GRP for {file_name}.')
            continue

        report, issues = calc.build_composite_report(raw, cmap, file_name, default_medium)
        if len(issues):
            composite_issues.append(issues)
        if report.empty:
            st.warning(f'No valid calculation rows found in {file_name}.')
            continue
        composite_reports.append(report)

    if not composite_reports:
        st.stop()

    media = pd.concat(composite_reports, ignore_index=True)
    report_issues = pd.concat(composite_issues, ignore_index=True) if composite_issues else pd.DataFrame()
    render_results(
        media,
        ratings=None,
        invalid_ratings=pd.DataFrame(),
        report_issues=report_issues,
        dup_keys=pd.DataFrame(),
        result_header='2. Results',
        row_label='Calculation rows',
        matched_label='Calculated rows',
        unmatched_label='Rows needing match review',
        input_issues_label='Excluded rows',
        input_issues_help='Composite rows excluded from calculations, usually total rows or rows missing required fields.',
        progress_label='Calculation coverage',
        export_file_name='Mediapulse_Composite_GRP_SOV_results.xlsx',
    )
    st.stop()

st.header('1. Programme Ratings')
ratings_file = st.file_uploader('Upload programme ratings (.xlsx, .xls, or .csv)', type=calc.ALLOWED_UPLOAD_TYPES, key='ratings')

if not ratings_file:
    st.stop()

try:
    ratings_raw = load_tabular_with_controls(
        ratings_file,
        'ratings',
        ['medium', 'channel', 'day', 'programme', 'rating', 'source'],
    )
except Exception as e:
    st.error(f'Could not read ratings file:\n\n{calc.friendly_upload_error(e)}')
    st.stop()

st.write('Map the ratings fields:')
rmap = mapping_ui(ratings_raw, 'ratings', ['channel', 'day', 'programme', 'rating'], ['medium', 'source'])
ratings_default_medium = default_medium_selector(rmap, 'ratings_default_medium')
render_mapping_review(
    ratings_raw,
    rmap,
    'ratings_review',
    ['channel', 'day', 'programme', 'rating'],
    ['medium', 'source'],
    numeric_fields=['rating'],
    defaults=default_values_for_mapping(rmap, ratings_default_medium),
)
if any(rmap[x] == '-- none --' for x in ['channel', 'day', 'programme', 'rating']):
    st.warning('Map all required ratings fields to continue.')
    st.stop()

ratings, invalid_ratings, dup_keys, ratings_lookup = calc.build_ratings_lookup(ratings_raw, rmap, ratings_default_medium)
if ratings.empty:
    st.error('No valid ratings found. Ratings must be numeric values from 0 to 100.')
    st.stop()

m1, m2, m3 = st.columns(3)
m1.metric('Ratings rows', f'{len(ratings):,}')
m2.metric('Unique rating keys', f'{ratings_lookup["Match Key"].nunique():,}')
m3.metric('Duplicate rating keys', f'{len(dup_keys):,}')
if len(dup_keys):
    st.warning('Duplicate rating keys found. The app uses the average rating for duplicate keys. Review these before final reporting.')

st.header('2. Brand Media Reports')
brand_files = st.file_uploader(
    'Upload one or more brand reports (.xlsx, .xls, or .csv)',
    type=calc.ALLOWED_UPLOAD_TYPES,
    accept_multiple_files=True,
    key='brands',
)
if not brand_files:
    st.stop()

reuse_first_mapping = st.checkbox('Reuse the first compatible brand mapping for the remaining reports', value=True)

all_reports = []
report_issue_frames = []
first_brand_mapping = None
for idx, uploaded in enumerate(brand_files):
    file_name = calc.uploaded_display_name(uploaded)
    st.subheader(f'Report {idx + 1}: {file_name}')
    try:
        raw = load_tabular_with_controls(
            uploaded,
            f'brand_{idx}',
            ['brand', 'medium', 'date', 'day', 'channel', 'programme', 'spots'],
        )
    except Exception as e:
        st.error(f'Could not read {file_name}:\n\n{calc.friendly_upload_error(e)}')
        continue

    can_reuse = (
        reuse_first_mapping
        and first_brand_mapping is not None
        and all(col == '-- none --' or col in raw.columns for col in first_brand_mapping.values())
    )
    if can_reuse:
        bmap = first_brand_mapping.copy()
        st.caption('Using the first report mapping for this compatible file.')
        with st.expander('Override mapping for this report'):
            if st.checkbox('Use a custom mapping for this report', key=f'brand_override_{idx}'):
                bmap = mapping_ui(raw, f'brand_{idx}', ['channel', 'programme', 'spots'], ['brand', 'medium', 'date', 'day'])
    else:
        bmap = mapping_ui(raw, f'brand_{idx}', ['channel', 'programme', 'spots'], ['brand', 'medium', 'date', 'day'])

    brand_default_medium = default_medium_selector(bmap, f'brand_{idx}_default_medium')
    render_mapping_review(
        raw,
        bmap,
        f'brand_{idx}_review',
        ['channel', 'programme', 'spots'],
        ['brand', 'medium', 'date', 'day'],
        numeric_fields=['spots'],
        defaults=default_values_for_mapping(bmap, brand_default_medium, file_name),
    )

    required_missing = [x for x in ['channel', 'programme', 'spots'] if bmap[x] == '-- none --']
    if required_missing:
        st.warning(f'Map required fields for {file_name}: {", ".join(required_missing)}')
        continue
    if bmap['date'] == '-- none --' and bmap['day'] == '-- none --':
        st.warning(f'Map either Date or Day for {file_name}.')
        continue

    if first_brand_mapping is None:
        first_brand_mapping = bmap.copy()

    report, issues = calc.build_brand_report(raw, bmap, file_name, brand_default_medium)
    if len(issues):
        report_issue_frames.append(issues)
    if report.empty:
        st.warning(f'No valid calculation rows found in {file_name}.')
        continue
    all_reports.append(report)

if not all_reports:
    st.stop()

media = calc.match_reports_to_ratings(all_reports, ratings_lookup)
report_issues = pd.concat(report_issue_frames, ignore_index=True) if report_issue_frames else pd.DataFrame()
render_results(
    media,
    ratings=ratings,
    invalid_ratings=invalid_ratings,
    report_issues=report_issues,
    dup_keys=dup_keys,
    row_label='Report rows',
    matched_label='Matched rows',
    unmatched_label='Unmatched rows',
    input_issues_label='Input issues',
    input_issues_help='Ratings or brand-report rows excluded because required values were missing or invalid.',
    progress_label='Match rate',
    export_file_name='Mediapulse_Matched_GRP_SOV_results.xlsx',
)
