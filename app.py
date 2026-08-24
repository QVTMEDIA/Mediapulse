import io
import hmac
import json
import os
import re
import time
import uuid
from datetime import date, datetime
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

import grp_calculator as calc
import project_store

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
    'time_band': 'Time / Time Band',
    'rate': 'Rate',
    'cost': 'Cost',
}
PASSWORD_SECRET_EXAMPLE = 'APP_PASSWORD = "replace-with-a-strong-password"'
PROJECT_STATUS_OPTIONS = ['Setup', 'Data Review', 'Complete']
MEDIA_TYPE_OPTIONS = ['TV', 'Radio']
PROJECTS_STATE_KEY = 'projects'
ACTIVE_PROJECT_STATE_KEY = 'active_project_id'
PROJECT_STORE_LOADED_STATE_KEY = 'project_store_loaded'
PROJECT_STORE_ERROR_STATE_KEY = 'project_store_error'
PROJECT_MANIFEST_FILE_NAME = 'mediapulse_projects_manifest.json'
DEFAULT_PROJECT_DB_PATH = Path('.streamlit') / 'mediapulse_projects.db'


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
        render_password_disabled_notice()
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


def render_password_disabled_notice():
    st.warning('Password gate is disabled. Add a password before sharing this deployment.')
    with st.expander('Set up the password gate', expanded=True):
        st.markdown(
            'For Streamlit Cloud, open **Manage app**, then **Settings**, then **Secrets**. '
            'Paste this secret and save it:'
        )
        st.code(PASSWORD_SECRET_EXAMPLE, language='toml')
        st.markdown(
            'For local development, set `GRP_APP_PASSWORD` before running `streamlit run app.py`.'
        )


def clear_auth_state():
    for key in ['authenticated', 'authenticated_at', 'failed_login_attempts', 'locked_until']:
        st.session_state.pop(key, None)


def parse_project_date(value, fallback=None):
    fallback = fallback or date.today()
    if isinstance(value, date):
        return value
    if value:
        try:
            return datetime.strptime(str(value), '%Y-%m-%d').date()
        except ValueError:
            return fallback
    return fallback


def project_timestamp():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def project_id():
    return f'MP-{uuid.uuid4().hex[:8].upper()}'


def configured_project_db_path():
    env_path = os.environ.get('MEDIAPULSE_PROJECT_DB', '').strip()
    if env_path:
        return env_path
    try:
        secret_path = st.secrets.get('PROJECT_DB_PATH', '')
    except Exception:
        secret_path = ''
    return str(secret_path).strip() or str(DEFAULT_PROJECT_DB_PATH)


def record_project_store_error(exc):
    st.session_state[PROJECT_STORE_ERROR_STATE_KEY] = str(exc)


def clear_project_store_error():
    st.session_state.pop(PROJECT_STORE_ERROR_STATE_KEY, None)


def load_persisted_projects():
    try:
        projects = project_store.load_projects(configured_project_db_path())
    except Exception as exc:
        record_project_store_error(exc)
        return {}
    clear_project_store_error()
    return projects


def persist_project(project):
    try:
        project_store.upsert_project(configured_project_db_path(), project)
    except Exception as exc:
        record_project_store_error(exc)
        return False
    clear_project_store_error()
    return True


def persist_project_deletion(project_id_value):
    try:
        project_store.delete_project(configured_project_db_path(), project_id_value)
    except Exception as exc:
        record_project_store_error(exc)
        return False
    clear_project_store_error()
    return True


def render_project_storage_notice():
    store_error = st.session_state.get(PROJECT_STORE_ERROR_STATE_KEY)
    if store_error:
        st.warning(
            'Project database is unavailable, so project metadata is only kept in this browser session. '
            f'Error: {store_error}'
        )
        return
    st.info(
        'Project metadata is saved to a local SQLite store for this deployment. Export a manifest before '
        'redeploying or moving the app; use Supabase/Postgres later for durable multi-user storage.'
    )


def default_project_info():
    today = date.today()
    timestamp = project_timestamp()
    return {
        'project_id': project_id(),
        'project_name': '',
        'project_owner': '',
        'client': '',
        'category': '',
        'market': 'Nigeria',
        'start_date': today,
        'end_date': today,
        'target_audience': '',
        'media_types': MEDIA_TYPE_OPTIONS.copy(),
        'ratings_provider': '',
        'ratings_period': '',
        'status': 'Setup',
        'archived': False,
        'created_at': timestamp,
        'updated_at': timestamp,
        'notes': '',
    }


def project_bool(value):
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'y', 'archived'}
    return bool(value)


def normalize_project_info(values, touch=True):
    project = values.copy()
    project['project_name'] = str(project.get('project_name', '')).strip()
    project['project_owner'] = str(project.get('project_owner', '')).strip()
    project['client'] = str(project.get('client', '')).strip()
    project['category'] = str(project.get('category', '')).strip()
    project['market'] = str(project.get('market', '')).strip()
    project['target_audience'] = str(project.get('target_audience', '')).strip()
    project['ratings_provider'] = str(project.get('ratings_provider', '')).strip()
    project['ratings_period'] = str(project.get('ratings_period', '')).strip()
    project['notes'] = str(project.get('notes', '')).strip()
    media_types = project.get('media_types') or []
    if isinstance(media_types, str):
        media_types = [item.strip() for item in media_types.split(',')]
    elif not isinstance(media_types, (list, tuple, set)):
        media_types = [media_types]
    project['media_types'] = [media for media in list(media_types) if str(media).strip()]
    project['start_date'] = str(parse_project_date(project.get('start_date')))
    project['end_date'] = str(parse_project_date(project.get('end_date')))
    if not project.get('project_id'):
        project['project_id'] = project_id()
    status = str(project.get('status', 'Setup')).strip()
    if status == 'Archived':
        project['archived'] = True
        status = 'Setup'
    project['archived'] = project_bool(project.get('archived'))
    if status not in PROJECT_STATUS_OPTIONS:
        project['status'] = 'Setup'
    else:
        project['status'] = status
    timestamp = project_timestamp()
    project['created_at'] = str(project.get('created_at') or timestamp)
    project['updated_at'] = timestamp if touch or not project.get('updated_at') else str(project.get('updated_at'))
    return project


def project_setup_error(project):
    if not project.get('project_name'):
        return 'Project Name is required.'
    if parse_project_date(project.get('end_date')) < parse_project_date(project.get('start_date')):
        return 'End Date must be on or after Start Date.'
    return ''


def ensure_projects_state():
    projects = st.session_state.get(PROJECTS_STATE_KEY)
    if not isinstance(projects, dict):
        projects = load_persisted_projects()
        st.session_state[PROJECT_STORE_LOADED_STATE_KEY] = True
    elif not st.session_state.get(PROJECT_STORE_LOADED_STATE_KEY):
        persisted_projects = load_persisted_projects()
        persisted_projects.update(projects)
        projects = persisted_projects
        st.session_state[PROJECT_STORE_LOADED_STATE_KEY] = True

    legacy_project = st.session_state.pop('project_info', None)
    if legacy_project:
        migrated_project = normalize_project_info(legacy_project, touch=False)
        projects[migrated_project['project_id']] = migrated_project
        persist_project(migrated_project)
        st.session_state[ACTIVE_PROJECT_STATE_KEY] = migrated_project['project_id']

    active_project_id = st.session_state.get(ACTIVE_PROJECT_STATE_KEY)
    if active_project_id and active_project_id not in projects:
        st.session_state.pop(ACTIVE_PROJECT_STATE_KEY, None)

    st.session_state[PROJECTS_STATE_KEY] = projects
    return projects


def active_project_info():
    projects = ensure_projects_state()
    return projects.get(st.session_state.get(ACTIVE_PROJECT_STATE_KEY))


def save_project(project, make_active=True):
    projects = ensure_projects_state()
    normalized_project = normalize_project_info(project)
    projects[normalized_project['project_id']] = normalized_project
    persist_project(normalized_project)
    st.session_state[PROJECTS_STATE_KEY] = projects
    if make_active:
        st.session_state[ACTIVE_PROJECT_STATE_KEY] = normalized_project['project_id']
    return normalized_project


def project_period(project):
    start_date = project.get('start_date', '')
    end_date = project.get('end_date', '')
    if start_date and end_date:
        return f'{start_date} to {end_date}'
    return start_date or end_date or 'No dates set'


def project_status_label(project):
    if project.get('archived'):
        return f"Archived / {project.get('status', 'Setup')}"
    return project.get('status', 'Setup')


def duplicate_project(project):
    duplicated = project.copy()
    timestamp = project_timestamp()
    duplicated['project_id'] = project_id()
    duplicated['project_name'] = f"{project.get('project_name', 'Untitled project')} Copy"
    duplicated['archived'] = False
    duplicated['created_at'] = timestamp
    duplicated['updated_at'] = timestamp
    return duplicated


def filtered_projects(projects, search, status_filter):
    search = search.strip().lower()
    visible_projects = []
    for project in projects.values():
        haystack = ' '.join(
            str(project.get(field, ''))
            for field in ['project_name', 'client', 'category', 'market', 'project_owner', 'target_audience']
        ).lower()
        if search and search not in haystack:
            continue
        if status_filter == 'Active projects' and project.get('archived'):
            continue
        if status_filter == 'Archived' and not project.get('archived'):
            continue
        if status_filter in PROJECT_STATUS_OPTIONS and (
            project.get('archived') or project.get('status') != status_filter
        ):
            continue
        visible_projects.append(project)
    return sorted(visible_projects, key=lambda item: item.get('updated_at', ''), reverse=True)


def import_projects_from_payload(payload):
    imported_projects = calc.projects_from_manifest(payload)
    projects = ensure_projects_state()
    imported_count = 0
    for raw_project in imported_projects:
        project = normalize_project_info(raw_project, touch=False)
        if not project.get('project_name'):
            project['project_name'] = 'Imported project'
        if project['project_id'] in projects:
            project['project_id'] = project_id()
        projects[project['project_id']] = project
        persist_project(project)
        imported_count += 1
    st.session_state[PROJECTS_STATE_KEY] = projects
    return imported_count


def render_project_form(defaults, form_key, submit_label):
    defaults = defaults or default_project_info()
    with st.form(form_key):
        st.subheader('Project Setup')
        project_name = st.text_input('Project Name *', value=defaults.get('project_name', ''))
        form_cols = st.columns(2)
        with form_cols[0]:
            project_owner = st.text_input('Project Owner', value=defaults.get('project_owner', ''))
            client = st.text_input('Client', value=defaults.get('client', ''))
            category = st.text_input('Category', value=defaults.get('category', ''))
            market = st.text_input('Market', value=defaults.get('market', 'Nigeria'))
            start_date = st.date_input('Start Date', value=parse_project_date(defaults.get('start_date')))
        with form_cols[1]:
            target_audience = st.text_input('Target Audience', value=defaults.get('target_audience', ''))
            ratings_provider = st.text_input('Ratings Provider', value=defaults.get('ratings_provider', ''))
            ratings_period = st.text_input('Ratings Period', value=defaults.get('ratings_period', ''))
            end_date = st.date_input('End Date', value=parse_project_date(defaults.get('end_date')))
        media_types = st.multiselect(
            'Media Types',
            MEDIA_TYPE_OPTIONS,
            default=[media for media in defaults.get('media_types', MEDIA_TYPE_OPTIONS) if media in MEDIA_TYPE_OPTIONS],
        )
        status = st.selectbox(
            'Project Status',
            PROJECT_STATUS_OPTIONS,
            index=PROJECT_STATUS_OPTIONS.index(defaults.get('status', 'Setup')) if defaults.get('status', 'Setup') in PROJECT_STATUS_OPTIONS else 0,
        )
        notes = st.text_area('Notes', value=defaults.get('notes', ''))
        submitted = st.form_submit_button(submit_label)

    if not submitted:
        return None
    return normalize_project_info({
        'project_id': defaults.get('project_id'),
        'project_name': project_name,
        'project_owner': project_owner,
        'client': client,
        'category': category,
        'market': market,
        'start_date': start_date,
        'end_date': end_date,
        'target_audience': target_audience,
        'media_types': media_types,
        'ratings_provider': ratings_provider,
        'ratings_period': ratings_period,
        'status': status,
        'archived': defaults.get('archived', False),
        'created_at': defaults.get('created_at'),
        'updated_at': defaults.get('updated_at'),
        'notes': notes,
    })


def render_project_row(project):
    project_key = project['project_id']
    with st.container():
        columns = st.columns([3, 1.4, 1.4, 1.4, 1.2])
        with columns[0]:
            st.markdown(f"**{project.get('project_name', 'Untitled project')}**")
            metadata = [
                project.get('client', ''),
                project.get('category', ''),
                project.get('market', ''),
            ]
            metadata = [item for item in metadata if item]
            if metadata:
                st.caption(' | '.join(metadata))
            st.caption(f"Period: {project_period(project)}")
        with columns[1]:
            st.caption('Status')
            st.write(project_status_label(project))
        with columns[2]:
            st.caption('Media')
            st.write(', '.join(project.get('media_types') or []) or 'Not set')
        with columns[3]:
            st.caption('Updated')
            st.write(project.get('updated_at', ''))
        with columns[4]:
            if st.button('Open', key=f'open_{project_key}'):
                st.session_state[ACTIVE_PROJECT_STATE_KEY] = project_key
                st.rerun()
            if st.button('Duplicate', key=f'duplicate_{project_key}'):
                save_project(duplicate_project(project), make_active=False)
                st.rerun()

        action_columns = st.columns([1, 1, 4])
        archive_label = 'Restore' if project.get('archived') else 'Archive'
        with action_columns[0]:
            if st.button(archive_label, key=f'archive_{project_key}'):
                projects = ensure_projects_state()
                projects[project_key]['archived'] = not projects[project_key].get('archived')
                projects[project_key]['updated_at'] = project_timestamp()
                persist_project(projects[project_key])
                st.session_state[PROJECTS_STATE_KEY] = projects
                st.rerun()
        with action_columns[1]:
            delete_key = f'confirm_delete_{project_key}'
            if st.session_state.get('delete_project_id') == project_key:
                if st.button('Confirm delete', key=delete_key):
                    projects = ensure_projects_state()
                    projects.pop(project_key, None)
                    if st.session_state.get(ACTIVE_PROJECT_STATE_KEY) == project_key:
                        st.session_state.pop(ACTIVE_PROJECT_STATE_KEY, None)
                    st.session_state.pop('delete_project_id', None)
                    persist_project_deletion(project_key)
                    st.session_state[PROJECTS_STATE_KEY] = projects
                    st.rerun()
            elif st.button('Delete', key=f'delete_{project_key}'):
                st.session_state['delete_project_id'] = project_key
                st.rerun()
        st.divider()


def render_projects_home(projects):
    st.header('Home / Projects')
    render_project_storage_notice()

    metric_columns = st.columns(3)
    archived_count = sum(1 for project in projects.values() if project.get('archived'))
    metric_columns[0].metric('Projects', len(projects))
    metric_columns[1].metric('Active', len(projects) - archived_count)
    metric_columns[2].metric('Archived', archived_count)

    utility_columns = st.columns([1, 1])
    with utility_columns[0]:
        manifest = calc.project_manifest(projects, exported_at=project_timestamp())
        st.download_button(
            'Export project manifest',
            data=json.dumps(manifest, indent=2),
            file_name=PROJECT_MANIFEST_FILE_NAME,
            mime='application/json',
            disabled=not bool(projects),
        )
    with utility_columns[1]:
        with st.form('import_project_manifest'):
            manifest_upload = st.file_uploader('Import project manifest (.json)', type=['json'])
            import_submitted = st.form_submit_button('Import manifest')
        if import_submitted:
            if not manifest_upload:
                st.error('Choose a JSON project manifest to import.')
            else:
                try:
                    payload = json.load(manifest_upload)
                    imported_count = import_projects_from_payload(payload)
                except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                    st.error(f'Could not import project manifest: {exc}')
                else:
                    st.success(f'Imported {imported_count} project(s).')
                    st.rerun()

    with st.expander('Create project', expanded=not bool(projects)):
        created_project = render_project_form(default_project_info(), 'create_project', 'Create project workspace')
        if created_project:
            error = project_setup_error(created_project)
            if error:
                st.error(error)
            else:
                save_project(created_project)
                st.rerun()

    if not projects:
        st.info('Create a project workspace to start uploading ratings and media reports.')
        st.stop()

    filter_columns = st.columns([2, 1])
    search = filter_columns[0].text_input('Search projects', value='')
    status_filter = filter_columns[1].selectbox(
        'Filter',
        ['All', 'Active projects', 'Archived'] + PROJECT_STATUS_OPTIONS,
    )
    visible_projects = filtered_projects(projects, search, status_filter)

    if not visible_projects:
        st.info('No projects match the current filters.')
        st.stop()

    for project in visible_projects:
        render_project_row(project)

    st.stop()


def render_project_workspace():
    projects = ensure_projects_state()
    project_info = active_project_info()
    if not project_info:
        render_projects_home(projects)

    with st.sidebar:
        st.header('Project')
        st.markdown(f"**{project_info.get('project_name', 'Untitled project')}**")
        st.caption(project_status_label(project_info))
        if project_info.get('category'):
            st.caption(f"Category: {project_info['category']}")
        if project_info.get('market'):
            st.caption(f"Market: {project_info['market']}")
        if st.button('Close project'):
            st.session_state.pop(ACTIVE_PROJECT_STATE_KEY, None)
            st.rerun()

    with st.expander('Project setup', expanded=False):
        updated_project = render_project_form(project_info, 'update_project', 'Update project')
        if updated_project:
            error = project_setup_error(updated_project)
            if error:
                st.error(error)
            else:
                project_info = save_project(updated_project)
                st.success('Project updated.')
                st.rerun()

    return project_info


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


def uploaded_file_signature(uploaded):
    return (
        calc.uploaded_display_name(uploaded),
        calc.upload_size(uploaded),
    )


def uploaded_files_signature(uploaded_files):
    return tuple(uploaded_file_signature(uploaded) for uploaded in uploaded_files)


def mapping_signature(mapping):
    return tuple(sorted((field, str(column)) for field, column in mapping.items()))


def reset_stage_if_inputs_changed(key, signature):
    signature_key = f'{key}_signature'
    ready_key = f'{key}_ready'
    if st.session_state.get(signature_key) != signature:
        st.session_state[signature_key] = signature
        st.session_state[ready_key] = False
    return ready_key


def require_stage_action(key, signature, button_label, waiting_message):
    ready_key = reset_stage_if_inputs_changed(key, signature)
    if st.session_state.get(ready_key):
        return True
    st.info(waiting_message)
    if st.button(button_label, key=f'{key}_button'):
        st.session_state[ready_key] = True
        return True
    return False


def render_upload_preflight(uploaded_files, key):
    rows = []
    valid = True
    for uploaded in uploaded_files:
        file_name = calc.uploaded_display_name(uploaded)
        size_mb = calc.upload_size(uploaded) / (1024 * 1024)
        try:
            calc.validate_uploaded_file(uploaded)
            sheets = calc.excel_workbook_profile(uploaded)
            if sheets:
                largest_sheet = max((sheet for sheet in sheets if sheet.get('cells')), key=lambda sheet: sheet['cells'], default=None)
                rows.append({
                    'File': file_name,
                    'Size MB': round(size_mb, 2),
                    'Sheets': len(sheets),
                    'Largest Sheet': largest_sheet['name'] if largest_sheet else '',
                    'Rows': largest_sheet['rows'] if largest_sheet else '',
                    'Columns': largest_sheet['columns'] if largest_sheet else '',
                    'Status': 'Ready',
                })
            else:
                rows.append({
                    'File': file_name,
                    'Size MB': round(size_mb, 2),
                    'Sheets': '',
                    'Largest Sheet': '',
                    'Rows': '',
                    'Columns': '',
                    'Status': 'Ready',
                })
        except Exception as exc:
            valid = False
            rows.append({
                'File': file_name,
                'Size MB': round(size_mb, 2),
                'Sheets': '',
                'Largest Sheet': '',
                'Rows': '',
                'Columns': '',
                'Status': 'Blocked',
            })
            st.error(f'Could not validate {file_name}:\n\n{calc.friendly_upload_error(exc)}')

    if rows:
        with st.expander('Upload preflight', expanded=True):
            st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)
    if not valid:
        st.stop()
    return require_stage_action(
        key,
        uploaded_files_signature(uploaded_files),
        'Continue to interpretation',
        'Files passed preflight. Continue when you are ready to inspect sheets, choose headers, and map columns.',
    )


def load_tabular_with_controls(uploaded, key, expected_fields, expanded=False):
    calc.validate_uploaded_file(uploaded)
    sheet_name = sheet_selector(uploaded, f'{key}_sheet')
    sheet_profile = calc.validate_uploaded_sheet(uploaded, sheet_name)
    if sheet_profile and sheet_profile.get('rows') and sheet_profile.get('columns'):
        st.caption(
            f"Preflight passed: worksheet '{sheet_profile['name']}' has about "
            f"{sheet_profile['rows']:,} rows x {sheet_profile['columns']:,} columns."
        )
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
    project_info=None,
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
        if project_info:
            calc.excel_safe_df(calc.project_info_frame(project_info)).to_excel(writer, sheet_name='Project Info', index=False)
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
project_info = render_project_workspace()

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
    st.caption('Separate example: one ratings file plus one or more brand activity files matched by station, day, programme, and time when available.')

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
    if not render_upload_preflight(composite_files, 'composite_preflight'):
        st.stop()

    composite_inputs = []
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

        composite_inputs.append((raw, cmap, file_name, default_medium))

    if not composite_inputs:
        st.stop()

    composite_signature = (
        uploaded_files_signature(composite_files),
        tuple((file_name, mapping_signature(cmap), default_medium) for _raw, cmap, file_name, default_medium in composite_inputs),
    )
    if not require_stage_action(
        'composite_calculate',
        composite_signature,
        'Run composite calculation',
        'Composite mapping is ready. Run calculation when you are ready to build the report.',
    ):
        st.stop()

    composite_reports = []
    composite_issues = []
    for raw, cmap, file_name, default_medium in composite_inputs:
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
        project_info=project_info,
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
if not render_upload_preflight([ratings_file], 'ratings_preflight'):
    st.stop()

try:
    ratings_raw = load_tabular_with_controls(
        ratings_file,
        'ratings',
        ['medium', 'channel', 'day', 'programme', 'rating', 'source', 'time_band'],
    )
except Exception as e:
    st.error(f'Could not read ratings file:\n\n{calc.friendly_upload_error(e)}')
    st.stop()

st.write('Map the ratings fields:')
rmap = mapping_ui(ratings_raw, 'ratings', ['channel', 'day', 'programme', 'rating'], ['medium', 'source', 'time_band'])
ratings_default_medium = default_medium_selector(rmap, 'ratings_default_medium')
render_mapping_review(
    ratings_raw,
    rmap,
    'ratings_review',
    ['channel', 'day', 'programme', 'rating'],
    ['medium', 'source', 'time_band'],
    numeric_fields=['rating'],
    defaults=default_values_for_mapping(rmap, ratings_default_medium),
)
if any(rmap[x] == '-- none --' for x in ['channel', 'day', 'programme', 'rating']):
    st.warning('Map all required ratings fields to continue.')
    st.stop()

ratings_signature = (uploaded_file_signature(ratings_file), mapping_signature(rmap), ratings_default_medium)
if not require_stage_action(
    'ratings_build',
    ratings_signature,
    'Build ratings table',
    'Ratings mapping is ready. Build the validated ratings table before moving to brand reports.',
):
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
if not render_upload_preflight(brand_files, 'brand_preflight'):
    st.stop()

reuse_first_mapping = st.checkbox('Reuse the first compatible brand mapping for the remaining reports', value=True)

brand_inputs = []
first_brand_mapping = None
for idx, uploaded in enumerate(brand_files):
    file_name = calc.uploaded_display_name(uploaded)
    st.subheader(f'Report {idx + 1}: {file_name}')
    try:
        raw = load_tabular_with_controls(
            uploaded,
            f'brand_{idx}',
            ['brand', 'medium', 'date', 'day', 'channel', 'programme', 'spots', 'time_band', 'rate', 'cost'],
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
                bmap = mapping_ui(raw, f'brand_{idx}', ['channel', 'programme', 'spots'], ['brand', 'medium', 'date', 'day', 'time_band', 'rate', 'cost'])
    else:
        bmap = mapping_ui(raw, f'brand_{idx}', ['channel', 'programme', 'spots'], ['brand', 'medium', 'date', 'day', 'time_band', 'rate', 'cost'])

    brand_default_medium = default_medium_selector(bmap, f'brand_{idx}_default_medium')
    render_mapping_review(
        raw,
        bmap,
        f'brand_{idx}_review',
        ['channel', 'programme', 'spots'],
        ['brand', 'medium', 'date', 'day', 'time_band', 'rate', 'cost'],
        numeric_fields=['spots', 'rate', 'cost'],
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

    brand_inputs.append((raw, bmap, file_name, brand_default_medium))

if not brand_inputs:
    st.stop()

brand_signature = (
    ratings_signature,
    uploaded_files_signature(brand_files),
    tuple((file_name, mapping_signature(bmap), default_medium) for _raw, bmap, file_name, default_medium in brand_inputs),
)
if not require_stage_action(
    'brand_calculate',
    brand_signature,
    'Run matching and calculation',
    'Brand mappings are ready. Run matching and calculation when you are ready to build the report.',
):
    st.stop()

all_reports = []
report_issue_frames = []
for raw, bmap, file_name, brand_default_medium in brand_inputs:
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
    project_info=project_info,
    row_label='Report rows',
    matched_label='Matched rows',
    unmatched_label='Unmatched rows',
    input_issues_label='Input issues',
    input_issues_help='Ratings or brand-report rows excluded because required values were missing or invalid.',
    progress_label='Match rate',
    export_file_name='Mediapulse_Matched_GRP_SOV_results.xlsx',
)
