import io
import unittest
from pathlib import Path

import pandas as pd

import grp_calculator as calc


ROOT = Path(__file__).resolve().parents[1]
COMPOSITE_PATH = Path(r'C:\Users\QVT-CREATIFF\Downloads\Composite 2026.xlsx')


class NamedBytes(io.BytesIO):
    def __init__(self, payload, name):
        super().__init__(payload)
        self.name = name


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


if __name__ == '__main__':
    unittest.main()
