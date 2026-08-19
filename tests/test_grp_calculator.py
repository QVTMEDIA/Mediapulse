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

    def test_xlsm_uploads_are_blocked(self):
        uploaded = NamedBytes(b'not a real workbook', 'macro_report.xlsm')
        with self.assertRaisesRegex(ValueError, 'Macro-enabled'):
            calc.validate_uploaded_file(uploaded)

    def test_excel_formula_values_are_escaped_for_export(self):
        df = pd.DataFrame({
            'Brand': ['=cmd', '+sum', '-bad', '@risk', 'safe'],
            'GRP': [1, 2, 3, 4, 5],
        })
        safe = calc.excel_safe_df(df)
        self.assertEqual(safe['Brand'].tolist(), ["'=cmd", "'+sum", "'-bad", "'@risk", 'safe'])
        self.assertEqual(safe['GRP'].tolist(), [1, 2, 3, 4, 5])


if __name__ == '__main__':
    unittest.main()
