import io
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import grp_calculator as calc


ROOT = Path(__file__).resolve().parents[1]
COMPOSITE_PATH = Path(r'C:\Users\QVT-CREATIFF\Downloads\Composite 2026.xlsx')


class NamedBytes(io.BytesIO):
    def __init__(self, payload, name):
        super().__init__(payload)
        self.name = name


def minimal_xlsx(sheet_dimensions):
    workbook_sheets = []
    workbook_rels = []
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as workbook:
        workbook.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types" />')
        workbook.writestr(
            '_rels/.rels',
            (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
                'Target="xl/workbook.xml" />'
                '</Relationships>'
            ),
        )
        for index, (sheet_name, dimension) in enumerate(sheet_dimensions, start=1):
            workbook_sheets.append(f'<sheet name="{sheet_name}" sheetId="{index}" r:id="rId{index}" />')
            workbook_rels.append(
                f'<Relationship Id="rId{index}" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                f'Target="worksheets/sheet{index}.xml" />'
            )
            workbook.writestr(
                f'xl/worksheets/sheet{index}.xml',
                (
                    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                    f'<dimension ref="{dimension}" />'
                    '<sheetData />'
                    '</worksheet>'
                ),
            )
        workbook.writestr(
            'xl/workbook.xml',
            (
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                f'<sheets>{"".join(workbook_sheets)}</sheets>'
                '</workbook>'
            ),
        )
        workbook.writestr(
            'xl/_rels/workbook.xml.rels',
            (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                f'{"".join(workbook_rels)}'
                '</Relationships>'
            ),
        )
    return buffer.getvalue()


class GrpCalculatorTests(unittest.TestCase):
    def test_separate_ratings_and_brand_reports_match_samples(self):
        ratings_raw = pd.read_excel(ROOT / 'sample_ratings.xlsx')
        brand_raw = pd.read_excel(ROOT / 'sample_brand_report.xlsx')

        rmap = {
            'medium': 'Medium',
            'channel': 'Channel / Station',
            'day': 'Day',
            'programme': 'Programme / Time Band',
            'rating': 'Rating (%)',
            'source': 'Source / Period',
        }
        bmap = {
            'brand': 'Brand',
            'medium': 'Medium',
            'date': 'Date',
            'day': 'Day',
            'channel': 'Channel / Station',
            'programme': 'Programme / Time Band',
            'spots': 'Spots',
        }

        ratings, invalid_ratings, dup_keys, ratings_lookup = calc.build_ratings_lookup(ratings_raw, rmap)
        report, report_issues = calc.build_brand_report(brand_raw, bmap, 'sample_brand_report.xlsx')
        media = calc.match_reports_to_ratings([report], ratings_lookup)
        summary, category_grps, suspicious_mediums = calc.summarize_media(media)

        self.assertEqual(len(ratings), 202)
        self.assertEqual(len(invalid_ratings), 0)
        self.assertEqual(len(dup_keys), 0)
        self.assertEqual(len(report), 202)
        self.assertEqual(len(report_issues), 0)
        self.assertEqual(int(media['Matched Rating (%)'].notna().sum()), 202)
        self.assertEqual(int(media['Match Status'].eq('NO RATING MATCH').sum()), 0)
        self.assertAlmostEqual(float(category_grps), 113.70, places=2)
        self.assertEqual(suspicious_mediums, [])
        self.assertAlmostEqual(float(summary.iloc[0]['Total GRPs']), 113.70, places=2)

    def test_unmatched_rows_get_rating_suggestions(self):
        ratings = pd.DataFrame({
            'Medium': ['TV', 'TV', 'TV'],
            'Channel / Station': ['Station A', 'Station A', 'Station B'],
            'Day': ['Mon', 'Mon', 'Tue'],
            'Programme / Time Band': ['Morning Show', 'Evening News', 'Morning Show'],
            'Rating (%)': [2.5, 3.0, 4.0],
        })
        ratings['Match Key'] = calc.make_key(
            ratings['Medium'],
            ratings['Channel / Station'],
            ratings['Day'],
            ratings['Programme / Time Band'],
        )
        media = pd.DataFrame({
            'Brand': ['Brand A', 'Brand A'],
            'Source File': ['brand.xlsx', 'brand.xlsx'],
            'Medium': ['TV', 'TV'],
            'Channel / Station': ['Station A', 'Station A'],
            'Day': ['Mon', 'Mon'],
            'Programme / Time Band': ['Morning Shw', 'Evening News'],
            'Match Status': ['NO RATING MATCH', 'MATCHED'],
            'Match Key': ['TV|STATION A|MON|MORNING SHW', 'TV|STATION A|MON|EVENING NEWS'],
        })

        suggestions = calc.build_unmatched_suggestions(media, ratings, max_suggestions_per_row=1, min_score=0.5)

        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions.loc[0, 'Input Programme / Time Band'], 'Morning Shw')
        self.assertEqual(suggestions.loc[0, 'Suggested Programme / Time Band'], 'Morning Show')
        self.assertEqual(suggestions.loc[0, 'Suggested Rating (%)'], 2.5)
        self.assertEqual(suggestions.loc[0, 'Confidence'], 'High')
        self.assertEqual(suggestions.loc[0, 'Suggestion Basis'], 'Same medium, channel, and day')

    def test_unrelated_station_with_matching_generic_programme_gets_no_suggestion(self):
        # Regression for a real false positive: two completely unrelated
        # stations ("Cool FM Lagos" vs a rating on "Human Rights FM Abuja")
        # scored 91-100% "High confidence" purely because both happened to
        # share the generic Programme value "ROS" (Run of Schedule -- no
        # specific programme). The "same medium and day" tier doesn't
        # require the channel to match at all, so with no station signal
        # blended into the score, a coincidental programme-text match was
        # enough to fabricate a confident-looking suggestion.
        ratings = pd.DataFrame({
            'Medium': ['Radio'],
            'Channel / Station': ['Human Rights FM Abuja'],
            'Day': ['Mon'],
            'Programme / Time Band': ['ROS'],
            'Rating (%)': [0.0],
        })
        ratings['Match Key'] = calc.make_key(
            ratings['Medium'], ratings['Channel / Station'], ratings['Day'], ratings['Programme / Time Band']
        )
        media = pd.DataFrame({
            'Brand': ['Brand A'],
            'Source File': ['spend.xlsx'],
            'Medium': ['Radio'],
            'Channel / Station': ['Cool FM Lagos'],
            'Day': ['Monday'],
            'Programme / Time Band': ['ROS'],
            'Match Status': ['NO RATING MATCH'],
            'Match Key': ['RADIO|COOL FM LAGOS|MON|ROS'],
        })

        suggestions = calc.build_unmatched_suggestions(media, ratings)

        self.assertEqual(len(suggestions), 0)

    def test_unmatched_suggestion_still_scores_high_for_a_real_station_near_match(self):
        # "AIT Lagos" is a real near-match for a rating on plain "AIT" --
        # station-similarity blending must not punish a station name that's
        # a superset of the rating's (extra city/state words), only one
        # that shares nothing with it. Mirrors the fixture in
        # services/api/tests/test_matches.py.
        ratings = pd.DataFrame({
            'Medium': ['TV'],
            'Channel / Station': ['AIT'],
            'Day': ['Tue'],
            'Programme / Time Band': ['News'],
            'Rating (%)': [2.1],
        })
        ratings['Match Key'] = calc.make_key(
            ratings['Medium'], ratings['Channel / Station'], ratings['Day'], ratings['Programme / Time Band']
        )
        media = pd.DataFrame({
            'Brand': ['Brand A'],
            'Source File': ['spend.xlsx'],
            'Medium': ['TV'],
            'Channel / Station': ['AIT Lagos'],
            'Day': ['Tuesday'],
            'Programme / Time Band': ['News'],
            'Match Status': ['NO RATING MATCH'],
            'Match Key': ['TV|AIT LAGOS|TUE|NEWS'],
        })

        suggestions = calc.build_unmatched_suggestions(media, ratings)

        self.assertEqual(len(suggestions), 1)
        self.assertAlmostEqual(suggestions.loc[0, 'Similarity Score'], 1.0)
        self.assertEqual(suggestions.loc[0, 'Confidence'], 'High')
        self.assertEqual(suggestions.loc[0, 'Suggestion Basis'], 'Same medium and day')

    def test_unmatched_suggestions_rank_by_similarity_before_candidate_order(self):
        ratings = pd.DataFrame({
            'Medium': ['TV', 'TV'],
            'Channel / Station': ['Station A', 'Station A'],
            'Day': ['Mon', 'Mon'],
            'Programme / Time Band': ['Bad Low Match', 'Morning Show'],
            'Rating (%)': [1.0, 2.5],
        })
        ratings['Match Key'] = calc.make_key(
            ratings['Medium'],
            ratings['Channel / Station'],
            ratings['Day'],
            ratings['Programme / Time Band'],
        )
        media = pd.DataFrame({
            'Brand': ['Brand A'],
            'Source File': ['brand.xlsx'],
            'Medium': ['TV'],
            'Channel / Station': ['Station A'],
            'Day': ['Mon'],
            'Programme / Time Band': ['Morning Shw'],
            'Match Status': ['NO RATING MATCH'],
            'Match Key': ['TV|STATION A|MON|MORNING SHW'],
        })

        suggestions = calc.build_unmatched_suggestions(media, ratings, max_suggestions_per_row=1, min_score=0.1)

        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions.loc[0, 'Suggested Programme / Time Band'], 'Morning Show')
        self.assertGreater(suggestions.loc[0, 'Similarity Score'], 0.8)

    def test_unmatched_suggestions_are_empty_without_ratings(self):
        media = pd.DataFrame({
            'Match Status': ['NO RATING MATCH'],
            'Programme / Time Band': ['Morning Show'],
        })

        suggestions = calc.build_unmatched_suggestions(media, None)

        self.assertEqual(suggestions.columns.tolist(), calc.SUGGESTION_COLUMNS)
        self.assertEqual(len(suggestions), 0)

    def test_program_column_is_not_detected_as_rating(self):
        self.assertIsNone(calc.detect_column(['Channel', 'Program', 'Spots'], 'rating'))

    def test_radio_spend_time_matches_rating_time_ranges(self):
        spend_raw = pd.DataFrame({
            'DATE': ['2025-10-05'],
            'DAY': ['Sunday'],
            'TIME': ['20:31:39'],
            'TIME BELT': ['PM'],
            'BRAND': ['IBUCAP'],
            'STATION': ['BOND FM LAGOS'],
            'PROGRAM': ['KOKO INU IWE IROYIN'],
            'MEDIA': ['Radio'],
            'SPOT': [1],
            'RATE': [8300],
        })
        rating_raw = pd.DataFrame({
            'Channel': ['Lagos, Bond 92.9 FM, Lagos'],
            'WD': ['Sun'],
            'Program': ['ROS'],
            'Time band': ['20:30:00-20:45:00'],
            'Spots': [1],
            'Rch %': [0.5],
        })
        spend_fields = ['channel', 'programme', 'spots', 'brand', 'medium', 'date', 'day', 'rate', 'cost', 'time_band']
        rating_fields = ['channel', 'programme', 'rating', 'medium', 'source', 'time_band', 'date', 'day']
        spend_mapping = {field: calc.detect_column(spend_raw.columns, field) or '-- none --' for field in spend_fields}
        rating_mapping = {field: calc.detect_column(rating_raw.columns, field) or '-- none --' for field in rating_fields}

        self.assertEqual(spend_mapping['time_band'], 'TIME')
        self.assertEqual(rating_mapping['rating'], 'Rch %')
        self.assertEqual(rating_mapping['time_band'], 'Time band')

        report, report_issues = calc.build_brand_report(spend_raw, spend_mapping, 'Data.xlsx')
        ratings, invalid_ratings, _dup_keys, ratings_lookup = calc.build_ratings_lookup(
            rating_raw, rating_mapping, default_medium='Radio'
        )
        media = calc.match_reports_to_ratings([report], ratings_lookup)

        self.assertEqual(len(report_issues), 0)
        self.assertEqual(len(invalid_ratings), 0)
        self.assertEqual(len(ratings), 1)
        self.assertEqual(media.loc[0, 'Match Status'], 'MATCHED')
        self.assertAlmostEqual(media.loc[0, 'Matched Rating (%)'], 0.5)
        self.assertAlmostEqual(media.loc[0, 'GRP'], 0.5)

    def test_station_normalization_drops_vendor_state_prefix(self):
        self.assertEqual(
            calc.normalize_station_for_match('Abia, Magic 102.9 FM, Aba'),
            calc.normalize_station_for_match('MAGIC FM ABA'),
        )
        self.assertEqual(
            calc.normalize_station_for_match('Oyo, Splash 105.5 FM, Ibadan'),
            calc.normalize_station_for_match('SPLASH FM IBADAN'),
        )

    def test_unmatched_suggestions_skip_incompatible_time_bands(self):
        ratings = pd.DataFrame({
            'Medium': ['Radio'],
            'Channel / Station': ['Lagos, Nigeria Info 99.3 FM, Lagos'],
            'Day': ['Mon'],
            'Programme / Time Band': ['ROS'],
            'Time Band': ['22:30:00-22:45:00'],
            'Rating (%)': [0.2],
        })
        ratings['Match Key'] = calc.make_key(
            ratings['Medium'],
            ratings['Channel / Station'],
            ratings['Day'],
            ratings['Programme / Time Band'],
        )
        media = pd.DataFrame({
            'Brand': ['Brand A'],
            'Source File': ['spend.xlsx'],
            'Medium': ['Radio'],
            'Channel / Station': ['NIGERIA INFO LAGOS'],
            'Day': ['Monday'],
            'Programme / Time Band': ['ROS'],
            'Daypart': ['02:33:22'],
            'Match Status': ['NO RATING MATCH'],
            'Match Key': ['RADIO|NIGERIA INFO LAGOS|MON|ROS'],
        })

        suggestions = calc.build_unmatched_suggestions(media, ratings, min_score=0.1)

        self.assertEqual(len(suggestions), 0)

    def test_compatible_time_slot_treats_two_ranges_as_overlap_not_containment(self):
        # Regression: compatible_time_slot/time_band_contains assumed the
        # media-side value was always a single instant (a spot's own logged
        # air time) being checked against a rating's coarser range. A source
        # file with no distinct programme column labels its own rows with a
        # coarse daypart/timeband range too (see
        # resolve_effective_programme) -- treating that range as an
        # unparseable single point used to fail closed even when both sides
        # describe the identical window, just in different text formats.
        self.assertTrue(calc.compatible_time_slot('0600-0900', '0600-0900'))
        self.assertTrue(calc.compatible_time_slot('06:00-09:00', '0600-0900'))
        self.assertTrue(calc.compatible_time_slot('06:00-09:00', '08:00-11:00'))  # partial overlap
        self.assertFalse(calc.compatible_time_slot('06:00-09:00', '18:00-21:00'))  # no overlap
        self.assertTrue(calc.compatible_time_slot('22:00-02:00', '23:00-01:00'))  # midnight wrap
        # Existing point-in-range behavior must be unaffected.
        self.assertTrue(calc.compatible_time_slot('14:32:10', '14:00-15:00'))
        self.assertFalse(calc.compatible_time_slot('16:32:10', '14:00-15:00'))

    def test_unmatched_suggestions_match_same_range_in_different_text_formats(self):
        # End-to-end reproduction of a real project shape: a radio file with
        # no named Programme column, only a Timeband range column (fed
        # through resolve_effective_programme's fallback into both Programme
        # and Time Band), where the ratings file and the spend file format
        # that same range slightly differently. Before the fix above, this
        # came back with zero suggestions no matter how low min_score was
        # set -- compatible_time_slot rejected it before similarity scoring
        # ever got a say.
        ratings = pd.DataFrame({
            'Medium': ['Radio'],
            'Channel / Station': ['Kiss FM Lagos'],
            'Day': ['Mon'],
            'Programme / Time Band': ['06:00-09:00'],
            'Time Band': ['06:00-09:00'],
            'Rating (%)': [1.0],
        })
        ratings['Match Key'] = calc.make_key(
            ratings['Medium'], ratings['Channel / Station'], ratings['Day'], ratings['Programme / Time Band']
        )
        media = pd.DataFrame({
            'Brand': ['Brand A'],
            'Source File': ['spend.xlsx'],
            'Medium': ['Radio'],
            'Channel / Station': ['Kiss FM Lagos'],
            'Day': ['Monday'],
            'Programme / Time Band': ['0600-0900'],
            'Daypart': ['0600-0900'],
            'Match Status': ['NO RATING MATCH'],
            'Match Key': ['RADIO|KISS FM LAGOS|MON|0600-0900'],
        })

        suggestions = calc.build_unmatched_suggestions(media, ratings)

        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions.loc[0, 'Suggested Rating (%)'], 1.0)

    def test_project_info_frame_formats_metadata_for_export(self):
        project = {
            'project_id': 'MP-1234',
            'project_name': 'Seasoning Category Q1 2026',
            'project_owner': 'Media Lead',
            'client': 'Sample Client',
            'category': 'Seasoning',
            'market': 'Nigeria',
            'start_date': '2026-01-01',
            'end_date': '2026-03-31',
            'target_audience': 'Adults 18-45 ABC',
            'media_types': ['TV', 'Radio'],
            'ratings_provider': 'Sample Provider',
            'ratings_period': 'Q1 2026',
            'status': 'Data Review',
            'archived': False,
            'created_at': '2026-08-19 10:00:00',
            'updated_at': '2026-08-19 10:30:00',
            'notes': 'Sample notes',
        }

        frame = calc.project_info_frame(project)
        values = dict(zip(frame['Field'], frame['Value']))

        self.assertEqual(values['Project ID'], 'MP-1234')
        self.assertEqual(values['Project Name'], 'Seasoning Category Q1 2026')
        self.assertEqual(values['Project Owner'], 'Media Lead')
        self.assertEqual(values['Media Types'], 'TV, Radio')
        self.assertEqual(values['Project Status'], 'Data Review')
        self.assertEqual(values['Archived'], False)
        self.assertEqual(values['Created At'], '2026-08-19 10:00:00')
        self.assertEqual(values['Updated At'], '2026-08-19 10:30:00')

    def test_project_manifest_round_trips_project_collection(self):
        projects = {
            'MP-1234': {
                'project_id': 'MP-1234',
                'project_name': 'Seasoning Category Q1 2026',
                'media_types': ['TV', 'Radio'],
                'start_date': pd.Timestamp('2026-01-01'),
            },
            'MP-5678': {
                'project_id': 'MP-5678',
                'project_name': 'Beverage Category Q2 2026',
                'media_types': ['TV'],
            },
        }

        manifest = calc.project_manifest(projects, exported_at='2026-08-19 12:00:00')
        restored = calc.projects_from_manifest(manifest)

        self.assertEqual(manifest['manifest_type'], 'mediapulse_projects')
        self.assertEqual(manifest['version'], 1)
        self.assertEqual(manifest['exported_at'], '2026-08-19 12:00:00')
        self.assertEqual(len(restored), 2)
        self.assertEqual(restored[0]['project_id'], 'MP-1234')
        self.assertEqual(restored[0]['start_date'], '2026-01-01T00:00:00')
        self.assertEqual(restored[1]['project_name'], 'Beverage Category Q2 2026')

    def test_projects_from_manifest_rejects_unknown_payload_shape(self):
        with self.assertRaisesRegex(ValueError, 'projects list'):
            calc.projects_from_manifest({'not_projects': []})

    @unittest.skipUnless(COMPOSITE_PATH.exists(), 'Composite 2026.xlsx is not available locally')
    def test_composite_report_excludes_total_row_and_uses_uploaded_grps(self):
        with COMPOSITE_PATH.open('rb') as uploaded:
            calc.validate_uploaded_file(uploaded)
            sheets = calc.list_excel_sheets(uploaded)
            self.assertEqual(sheets, ['National Comp per wk'])
            preview = calc.read_preview_table(uploaded, sheet_name=sheets[0])
            header_row = calc.infer_header_row(
                preview,
                ['brand', 'medium', 'date', 'day', 'channel', 'programme', 'spots', 'rating', 'grp'],
            )
            raw = calc.read_tabular(uploaded, sheet_name=sheets[0], header_row=header_row)

        self.assertEqual(header_row, 1)
        self.assertEqual(len(raw), 203)
        self.assertEqual(calc.detect_column(raw.columns, 'day'), 'WD')
        self.assertEqual(calc.detect_column(raw.columns, 'rating'), 'Rch %')
        self.assertEqual(calc.detect_column(raw.columns, 'grp'), 'Grps')

        mapping = {
            'brand': '-- none --',
            'medium': '-- none --',
            'date': '-- none --',
            'day': 'WD',
            'channel': 'Channel',
            'programme': 'Program',
            'spots': 'Spots',
            'rating': 'Rch %',
            'grp': 'Grps',
        }
        media, issues = calc.build_composite_report(raw, mapping, COMPOSITE_PATH.name, default_medium='TV')
        summary, category_grps, suspicious_mediums = calc.summarize_media(media)

        self.assertEqual(len(media), 202)
        self.assertEqual(len(issues), 1)
        self.assertEqual(int(media['Spots'].sum()), 202)
        self.assertEqual(media['GRP Source'].unique().tolist(), ['Uploaded GRP'])
        self.assertAlmostEqual(float(category_grps), 113.70, places=2)
        self.assertAlmostEqual(float(summary.iloc[0]['Total GRPs']), 113.70, places=2)
        self.assertEqual(suspicious_mediums, [])

    def test_composite_template_maps_and_calculates(self):
        template, sheet_name = calc.template_dataframe('composite')

        self.assertEqual(sheet_name, 'Composite Template')
        self.assertEqual(calc.detect_column(template.columns, 'day'), 'WD')
        self.assertEqual(calc.detect_column(template.columns, 'programme'), 'Program')
        self.assertEqual(calc.detect_column(template.columns, 'rating'), 'Rch %')
        self.assertEqual(calc.detect_column(template.columns, 'grp'), 'Grps')

        mapping = {
            'brand': 'Brand',
            'medium': 'Medium',
            'date': '-- none --',
            'day': 'WD',
            'channel': 'Channel',
            'programme': 'Program',
            'spots': 'Spots',
            'rating': 'Rch %',
            'grp': 'Grps',
        }
        media, issues = calc.build_composite_report(template, mapping, 'composite_report_template.xlsx')

        self.assertEqual(len(issues), 0)
        self.assertEqual(len(media), 1)
        self.assertEqual(media.loc[0, 'GRP Source'], 'Uploaded GRP')
        self.assertAlmostEqual(float(media.loc[0, 'GRP']), 2.5)

    def test_xlsm_uploads_are_blocked(self):
        uploaded = NamedBytes(b'not a real workbook', 'macro_report.xlsm')
        with self.assertRaisesRegex(ValueError, 'Macro-enabled'):
            calc.validate_uploaded_file(uploaded)

    def test_xlsx_preflight_lists_sheet_names_and_dimensions(self):
        uploaded = NamedBytes(minimal_xlsx([('Spend', 'A1:D12'), ('Ratings', 'A1:F40')]), 'media.xlsx')

        calc.validate_uploaded_file(uploaded)
        self.assertEqual(calc.list_excel_sheets(uploaded), ['Spend', 'Ratings'])

        profile = calc.validate_uploaded_sheet(uploaded, 'Ratings')
        self.assertEqual(profile['rows'], 40)
        self.assertEqual(profile['columns'], 6)
        self.assertEqual(profile['cells'], 240)

    def test_xlsx_preflight_rejects_large_used_range_before_pandas(self):
        uploaded = NamedBytes(minimal_xlsx([('Huge', 'A1:AZ100')]), 'huge.xlsx')
        original_limit = calc.MAX_UPLOAD_CELLS
        calc.MAX_UPLOAD_CELLS = 999
        try:
            with patch('grp_calculator.pd.read_excel') as read_excel:
                with self.assertRaisesRegex(ValueError, 'safe processing limit'):
                    calc.read_preview_table(uploaded, sheet_name='Huge')
                read_excel.assert_not_called()
        finally:
            calc.MAX_UPLOAD_CELLS = original_limit

    def test_xlsx_preflight_rejects_expanded_workbook_before_pandas(self):
        uploaded = NamedBytes(minimal_xlsx([('Spend', 'A1:D12')]), 'expanded.xlsx')
        original_limit = calc.MAX_EXCEL_EXPANDED_BYTES
        calc.MAX_EXCEL_EXPANDED_BYTES = 100
        try:
            with self.assertRaisesRegex(ValueError, 'expanded-workbook limit'):
                calc.validate_uploaded_file(uploaded)
        finally:
            calc.MAX_EXCEL_EXPANDED_BYTES = original_limit

    def test_derive_day_parses_iso_dates_without_dayfirst_ambiguity(self):
        # pandas' dayfirst=True (needed for DD/MM/YYYY-style input) silently
        # misreads an unambiguous ISO (YYYY-MM-DD) date whenever day and
        # month are both <=12 — e.g. "2026-01-05" read as May 1st instead of
        # January 5th — which would derive the wrong weekday, and therefore
        # the wrong match key, for any upload with only a Date column.
        dates = pd.Series(['2026-01-05', '2026-01-12', '05/01/2026'])
        self.assertEqual(calc.derive_day(dates).tolist(), ['MON', 'MON', 'MON'])

    def test_auth_session_timeout_and_lockout_helpers(self):
        self.assertTrue(calc.auth_session_is_valid(True, 100, 200, timeout_seconds=200))
        self.assertFalse(calc.auth_session_is_valid(True, 100, 400, timeout_seconds=200))
        self.assertFalse(calc.auth_session_is_valid(False, 100, 120, timeout_seconds=200))
        self.assertFalse(calc.auth_session_is_valid(True, None, 120, timeout_seconds=200))

        self.assertEqual(calc.lockout_remaining_seconds(165.1, 100), 66)
        self.assertEqual(calc.lockout_remaining_seconds(100, 120), 0)
        self.assertEqual(calc.lockout_remaining_seconds(None, 120), 0)

        failures, locked_until = calc.next_login_failure_state(3, 100, max_attempts=5, lockout_seconds=60)
        self.assertEqual(failures, 4)
        self.assertEqual(locked_until, 0)

        failures, locked_until = calc.next_login_failure_state(4, 100, max_attempts=5, lockout_seconds=60)
        self.assertEqual(failures, 5)
        self.assertEqual(locked_until, 160)

    def test_excel_formula_values_are_escaped_for_export(self):
        df = pd.DataFrame({
            'Brand': ['=cmd', '+sum', '-bad', '@risk', 'safe'],
            'GRP': [1, 2, 3, 4, 5],
        })
        safe = calc.excel_safe_df(df)
        self.assertEqual(safe['Brand'].tolist(), ["'=cmd", "'+sum", "'-bad", "'@risk", 'safe'])
        self.assertEqual(safe['GRP'].tolist(), [1, 2, 3, 4, 5])

    def test_mapping_profile_and_preview_show_interpretation_quality(self):
        raw = pd.DataFrame({
            'Channel': ['Station A', '', 'Station B'],
            'Program': ['Morning Show', 'Evening Show', ''],
            'Spots': ['2', 'bad', '3'],
        })
        raw.attrs['source_data_start_row'] = 5
        mapping = {
            'channel': 'Channel',
            'programme': 'Program',
            'spots': 'Spots',
            'medium': '-- none --',
        }

        profile = calc.profile_mapping(
            raw,
            mapping,
            ['channel', 'programme', 'spots', 'medium'],
            numeric_fields=['spots'],
        )
        spots_profile = profile.loc[profile['Field'].eq('spots')].iloc[0]
        medium_profile = profile.loc[profile['Field'].eq('medium')].iloc[0]

        self.assertEqual(int(spots_profile['Filled Rows']), 3)
        self.assertEqual(int(spots_profile['Numeric Rows']), 2)
        self.assertFalse(bool(medium_profile['Mapped']))
        self.assertEqual(
            calc.numeric_issue_fields_from_profile(profile, ['spots']),
            ['spots'],
        )
        self.assertEqual(
            calc.numeric_issue_fields_from_profile(profile, ['rating']),
            [],
        )
        self.assertEqual(
            calc.mapping_ready_rows(raw, mapping, ['channel', 'programme', 'spots'], numeric_fields=['spots']),
            1,
        )

        preview = calc.mapped_field_preview(
            raw,
            mapping,
            ['medium', 'channel', 'programme', 'spots'],
            defaults={'medium': 'TV'},
            labels={
                'medium': 'Medium',
                'channel': 'Channel / Station',
                'programme': 'Programme / Time Band',
                'spots': 'Spots',
            },
            numeric_fields=['spots'],
        )

        self.assertEqual(int(preview.loc[0, 'Input Row']), 5)
        self.assertEqual(preview.loc[1, 'Medium'], 'TV')
        self.assertTrue(pd.isna(preview.loc[1, 'Spots']))

    def test_export_summaries_capture_run_and_validation_counts(self):
        media = pd.DataFrame({
            'Brand': ['Brand A', 'Brand A', 'Brand B'],
            'Medium': ['TV', 'RADIO', 'TV'],
            'Spots': [2, 1, 3],
            'GRP': [10.0, 2.5, 0.0],
            'Match Status': ['MATCHED', 'MATCHED', 'NO RATING MATCH'],
        })
        summary, category_grps, suspicious_mediums = calc.summarize_media(media)
        invalid_ratings = pd.DataFrame({'Issue': ['Invalid or out-of-range rating']})
        report_issues = pd.DataFrame({'Issue': ['Invalid, zero, or negative spots']})
        dup_keys = pd.DataFrame({'Match Key': ['TV|A|MON|SHOW'], 'Rows': [2]})

        run_summary = calc.build_run_summary(
            media,
            summary,
            category_grps,
            ratings=pd.DataFrame({'Rating (%)': [1.0, 2.0]}),
            invalid_ratings=invalid_ratings,
            report_issues=report_issues,
            dup_keys=dup_keys,
            suspicious_mediums=suspicious_mediums,
            generated_at='2026-08-19 16:30:00',
        )
        validation_summary = calc.build_validation_summary(
            media,
            invalid_ratings=invalid_ratings,
            report_issues=report_issues,
            dup_keys=dup_keys,
            suspicious_mediums=suspicious_mediums,
        )

        metrics = dict(zip(run_summary['Metric'], run_summary['Value']))
        validations = dict(zip(validation_summary['Area'], validation_summary['Status']))

        self.assertEqual(metrics['Generated At'], '2026-08-19 16:30:00')
        self.assertEqual(metrics['Report rows'], 3)
        self.assertEqual(metrics['Matched rows'], 2)
        self.assertEqual(metrics['Unmatched rows'], 1)
        self.assertAlmostEqual(float(metrics['Total Category GRPs']), 12.5)
        self.assertEqual(metrics['Duplicate Rating Keys'], 1)
        self.assertEqual(validations['Duplicate rating keys'], 'Review')
        self.assertEqual(validations['Invalid ratings'], 'Review')
        self.assertEqual(validations['Report input issues'], 'Review')
        self.assertEqual(validations['Unmatched rows'], 'Review')
        self.assertEqual(validations['Suspicious medium values'], 'OK')

    def test_resolve_row_cost_prefers_direct_cost_over_rate(self):
        raw = pd.DataFrame({
            'Spots': [2, 3],
            'Cost': [1000.0, pd.NA],
            'Rate': [400.0, 250.0],
        })
        mapping = {'cost': 'Cost', 'rate': 'Rate'}
        cost = calc.resolve_row_cost(raw, mapping, raw['Spots'])
        # Row 0 has a direct Cost -> used as-is, Rate ignored even though present.
        self.assertEqual(cost.iloc[0], 1000.0)
        # Row 1 has no Cost -> falls back to Spots x Rate (3 x 250 = 750).
        self.assertEqual(cost.iloc[1], 750.0)

    def test_resolve_row_cost_is_nan_with_no_cost_or_rate_mapped(self):
        raw = pd.DataFrame({'Spots': [1, 2]})
        cost = calc.resolve_row_cost(raw, {}, raw['Spots'])
        self.assertTrue(cost.isna().all())

    def test_build_brand_report_carries_resolved_cost(self):
        raw = pd.DataFrame({
            'Channel': ['AIT', 'AIT'],
            'Programme': ['Morning Show', 'Morning Show'],
            'Day': ['Monday', 'Monday'],
            'Spots': [1, 2],
            'Rate': [6200, 6200],
        })
        mapping = {
            'brand': '-- none --', 'medium': '-- none --', 'date': '-- none --', 'day': 'Day',
            'channel': 'Channel', 'programme': 'Programme', 'spots': 'Spots', 'rate': 'Rate',
        }
        report, issues = calc.build_brand_report(raw, mapping, 'komix.csv', default_medium='Radio')
        self.assertEqual(len(issues), 0)
        self.assertEqual(report['Cost'].tolist(), [6200.0, 12400.0])

    def test_build_composite_report_carries_resolved_cost(self):
        raw = pd.DataFrame({
            'Channel': ['AIT'],
            'Programme': ['Morning Show'],
            'Day': ['Monday'],
            'Spots': [3],
            'Rating': [5.0],
            'Cost': [15000.0],
        })
        mapping = {
            'brand': '-- none --', 'medium': '-- none --', 'date': '-- none --', 'day': 'Day',
            'channel': 'Channel', 'programme': 'Programme', 'spots': 'Spots', 'rating': 'Rating',
            'grp': '-- none --', 'cost': 'Cost',
        }
        report, issues = calc.build_composite_report(raw, mapping, 'composite.csv', default_medium='TV')
        self.assertEqual(len(issues), 0)
        self.assertEqual(report['Cost'].tolist(), [15000.0])

    def test_build_report_cost_is_nan_when_no_spend_column_mapped(self):
        # No cost/rate mapping at all -> NaN, not 0 — "no spend data" and
        # "confirmed zero spend" are different things, same as GRP.
        raw = pd.DataFrame({
            'Channel': ['AIT'], 'Programme': ['Morning Show'], 'Day': ['Monday'], 'Spots': [1],
        })
        mapping = {
            'brand': '-- none --', 'medium': '-- none --', 'date': '-- none --', 'day': 'Day',
            'channel': 'Channel', 'programme': 'Programme', 'spots': 'Spots',
        }
        report, _issues = calc.build_brand_report(raw, mapping, 'no_spend.csv', default_medium='TV')
        self.assertTrue(pd.isna(report['Cost'].iloc[0]))

    def test_build_brand_report_captures_vendor_daypart_label_separately_from_programme(self):
        # 'time_band'/'Daypart' is a distinct field from 'programme' — a
        # file with both a Programme column and its own separate daypart
        # column (real vendor files often have one, e.g. "Time Belt") must
        # capture both, not have one clobber the other's detection.
        raw = pd.DataFrame({
            'Channel': ['ADABA FM'], 'Programme': ['ROS'], 'Time Belt': ['AM'],
            'Day': ['Monday'], 'Spots': [1],
        })
        mapping = {
            'brand': '-- none --', 'medium': '-- none --', 'date': '-- none --', 'day': 'Day',
            'channel': 'Channel', 'programme': 'Programme', 'spots': 'Spots', 'time_band': 'Time Belt',
        }
        report, issues = calc.build_brand_report(raw, mapping, 'daypart.csv', default_medium='Radio')
        self.assertEqual(len(issues), 0)
        self.assertEqual(report['Programme / Time Band'].iloc[0], 'ROS')
        self.assertEqual(report['Daypart'].iloc[0], 'AM')

    def test_detect_column_time_band_does_not_steal_the_day_column(self):
        # Regression test: detect_column's fuzzy fallback does substring
        # matching, and 'daypart' was briefly a 'time_band' synonym whose
        # substring ('day') falsely matched a plain 'Day' column whenever a
        # file had no real daypart column at all.
        columns = ['Channel', 'Programme', 'Day', 'Spots']
        self.assertIsNone(calc.detect_column(columns, 'time_band'))
        self.assertEqual(calc.detect_column(columns, 'day'), 'Day')

    def test_resolve_effective_programme_falls_back_to_time_band_when_programme_missing(self):
        # Regression test for a real incident: a real radio audience-reach
        # file (Channel/WD/Timeband/Rch %, no Programme column at all —
        # organized by time slot rather than named programme, a normal
        # shape for this kind of source) came back with every row rejected
        # as "Missing rating match field" once 'time_band' became a
        # separate field from 'programme' — 'programme' had nowhere left to
        # fall back to.
        raw = pd.DataFrame({'Channel': ['Cool FM'], 'Timeband': ['09:30-09:45'], 'WD': ['Sun']})
        mapping = {'programme': '-- none --', 'time_band': 'Timeband'}
        result = calc.resolve_effective_programme(raw, mapping)
        self.assertEqual(result.iloc[0], '09:30-09:45')

    def test_resolve_effective_programme_prefers_real_programme_when_present(self):
        raw = pd.DataFrame({'Programme': ['Prime Time'], 'Timeband': ['09:30-09:45']})
        mapping = {'programme': 'Programme', 'time_band': 'Timeband'}
        result = calc.resolve_effective_programme(raw, mapping)
        self.assertEqual(result.iloc[0], 'Prime Time')

    def test_resolve_effective_programme_blank_when_neither_mapped(self):
        raw = pd.DataFrame({'Channel': ['Cool FM']})
        mapping = {'programme': '-- none --'}
        result = calc.resolve_effective_programme(raw, mapping)
        self.assertEqual(result.iloc[0], '')

    def test_build_ratings_lookup_matches_rows_with_only_a_timeband_no_programme_column(self):
        # End-to-end reproduction of the real file: Channel/WD/Timeband/
        # Rch %, no Programme column. Every row must be kept and matchable,
        # not dropped.
        raw = pd.DataFrame({
            'Channel': ['Abuja, Cool FM, 96.9 Abuja', 'Edo, Speed 96.9 FM, Benin'],
            'WD': ['Sun', 'Fri'],
            'Timeband': ['09:30-09:45', '07:15-07:30'],
            'Rch %': [0.16, 0.92],
            'Medium': ['Radio', 'Radio'],
        })
        mapping = {
            'medium': 'Medium', 'channel': 'Channel', 'day': 'WD', 'programme': '-- none --',
            'time_band': 'Timeband', 'rating': 'Rch %', 'source': '-- none --',
        }
        ratings, invalid_ratings, dup_keys, lookup = calc.build_ratings_lookup(raw, mapping)
        self.assertEqual(len(invalid_ratings), 0)
        self.assertEqual(len(ratings), 2)
        self.assertEqual(ratings['Programme / Time Band'].tolist(), ['09:30-09:45', '07:15-07:30'])
        self.assertEqual(len(lookup), 2)  # both rows produced distinct, usable match keys

    def test_build_brand_report_daypart_is_blank_when_no_time_band_mapped(self):
        raw = pd.DataFrame({
            'Channel': ['AIT'], 'Programme': ['Morning Show'], 'Day': ['Monday'], 'Spots': [1],
        })
        mapping = {
            'brand': '-- none --', 'medium': '-- none --', 'date': '-- none --', 'day': 'Day',
            'channel': 'Channel', 'programme': 'Programme', 'spots': 'Spots',
        }
        report, _issues = calc.build_brand_report(raw, mapping, 'no_daypart.csv', default_medium='TV')
        self.assertEqual(report['Daypart'].iloc[0], '')

    def test_normalize_medium_type_recognizes_cable_tv_aliases(self):
        for value in ('Cable TV', 'Cable', 'DStv', 'GOtv', 'Pay TV', 'Satellite TV', 'cable'):
            self.assertEqual(calc.normalize_medium_type(value), 'CABLE TV', msg=value)
        # A bare/generic 'TV' — and explicit 'Terrestrial TV' — still means
        # the historical TV bucket, not Cable TV, so existing data with a
        # plain 'TV' medium doesn't silently reclassify.
        for value in ('TV', 'Television', 'Terrestrial TV', 'Terrestrial', 'FTA'):
            self.assertEqual(calc.normalize_medium_type(value), 'TV', msg=value)
        self.assertEqual(calc.normalize_medium_type('Radio'), 'RADIO')

    def test_summarize_media_splits_cable_tv_grps_separately(self):
        media = pd.DataFrame({
            'Brand': ['Brand A', 'Brand A', 'Brand A'],
            'Medium': ['TV', 'Cable TV', 'Radio'],
            'Spots': [1, 1, 1],
            'GRP': [10.0, 5.0, 2.0],
            'Match Status': ['MATCHED', 'MATCHED', 'MATCHED'],
        })
        summary, category_grps, suspicious_mediums = calc.summarize_media(media)
        row = summary.iloc[0]
        self.assertEqual(suspicious_mediums, [])
        self.assertAlmostEqual(float(row['TV GRPs']), 10.0)
        self.assertAlmostEqual(float(row['Cable TV GRPs']), 5.0)
        self.assertAlmostEqual(float(row['Radio GRPs']), 2.0)
        self.assertAlmostEqual(float(row['Total GRPs']), 17.0)
        self.assertAlmostEqual(float(category_grps), 17.0)


if __name__ == '__main__':
    unittest.main()
