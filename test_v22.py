import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

import ai_budget
from ai_budget import reserve, snapshot, BudgetBlocked
import scanner
from silver_engine import estimate_listing, detect_purity, extract_weight_grams
from ebay_client import normalize_item, EbayClient
from image_analyzer import analyze_image
from results_ui import title_link, table_data

EVIDENCE = dict(visual_confidence=95, silver_likelihood=95, plated_likelihood=0, likely_purity=.925,
                weighted_likelihood=0, hollow_handle_likelihood=0, knife_or_steel_blade_likelihood=0)


def candidate(item_id='one', title='Estate sterling spoons 420 grams'):
    row = dict(item_id=item_id, title=title, description='', price=25, shipping=5,
               image='https://example.com/photo.jpg', url='https://www.ebay.com/itm/123',
               hidden_sterling_score=0, image_evidence=None)
    scanner.apply_estimate(row, 50, .06, .92)
    return row


class ValuationTests(unittest.TestCase):
    def test_plate_variants_override_vision(self):
        for term in ['silverplate', 'silver plated', 'silver-plated', 'silver plate', 'EPNS', 'E.P.N.S.', 'silver-plating']:
            with self.subTest(term=term):
                e = estimate_listing('Sterling 925 420 grams', term, 5, 2, 50, image_evidence=EVIDENCE)
                self.assertIsNone(e.purity)
                self.assertIsNone(e.est_profit)
                self.assertFalse(scanner.is_alert(e.dict()))

    def test_value_formula(self):
        e = estimate_listing('sterling spoons 420 grams', '', 180, 12, 50, .06, .92)
        self.assertEqual(e.total_cost, 203.52)
        self.assertAlmostEqual(e.conservative_value, 420 / 31.1034768 * .925 * 50 * .92, places=2)
        self.assertEqual(e.silver_spot_used, 50)

    def test_weight_not_purity(self):
        self.assertIsNone(detect_purity('unmarked spoons 800 grams')[0])
        self.assertIsNone(detect_purity('pattern 1800')[0])

    def test_conflicting_weights_not_largest(self):
        self.assertIsNone(extract_weight_grams('420 grams, each spoon 35 grams')[0])
        self.assertEqual(extract_weight_grams('420 grams 14.82 oz')[0], 420)
        self.assertIsNone(extract_weight_grams('shipping weight 2 pounds')[0])

    def test_visual_construction_warnings(self):
        for name, warning, fraction in [('weighted_likelihood', 'weighted', .25), ('hollow_handle_likelihood', 'hollow', .35), ('knife_or_steel_blade_likelihood', 'knives', .35)]:
            e = estimate_listing('sterling 420 grams', '', 10, 0, 50, image_evidence=EVIDENCE | {name:90})
            self.assertEqual(e.recoverable_fraction, fraction)
            self.assertTrue(any(warning in r for r in e.risks))

    def test_unknown_shipping_suppresses_alert(self):
        row = normalize_item({'itemId':'x', 'title':'sterling 420g', 'price':{'value':'5','currency':'USD'}})
        scanner.apply_estimate(row, 50, 0, .92)
        self.assertFalse(scanner.is_alert(row))
        self.assertIsNone(row['conservative_value'])

    def test_links_are_clickable_and_escaped(self):
        row = candidate(title='Spoons [click](javascript:bad) <script>')
        self.assertIn('https://www.ebay.com/itm/123', title_link(row))
        self.assertIn('\\[click\\]', title_link(row))
        row['url'] = 'javascript:alert(1)'
        self.assertNotIn('javascript:alert', title_link(row))
        self.assertEqual(table_data([row], 75, 35).iloc[0]['Hidden Sterling'], '—')


class IsolatedBudget(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = patch.object(ai_budget, 'DB_PATH', Path(self.temp.name) / '.ai_usage.sqlite3')
        self.db.start()

    def tearDown(self):
        self.db.stop()
        self.temp.cleanup()


class BudgetTests(IsolatedBudget):
    def test_exact_boundary_and_zero(self):
        reserve('s', 10, .06, 1, 20, .03)
        reserve('s', 10, .06, 1, 20, .03)
        with self.assertRaises(BudgetBlocked):
            reserve('s', 10, .06, 1, 20, .03)
        for caps in [(0,1,20), (1,0,20), (1,1,0)]:
            with self.assertRaises(BudgetBlocked):
                reserve('z', 10, *caps, .03)
        self.assertEqual(snapshot('s')['estimated_scan_cost'], .06)

    def test_call_limit(self):
        reserve('s', 1, 10, 10, 10, .03)
        with self.assertRaisesRegex(BudgetBlocked, 'analysis limit'):
            reserve('s', 1, 10, 10, 10, .03)

    def test_daily_monthly_shared_across_scans(self):
        reserve('first', 10, 1, .03, .06, .03)
        with self.assertRaisesRegex(BudgetBlocked, 'Daily'):
            reserve('second', 10, 1, .03, .06, .03)
        reserve('second', 10, 1, 1, .06, .03)
        with self.assertRaisesRegex(BudgetBlocked, 'Monthly'):
            reserve('third', 10, 1, 1, .06, .03)

    def test_concurrent_reservations(self):
        def attempt(i):
            try:
                reserve(str(i), 10, 1, .03, 1, .03)
                return True
            except BudgetBlocked:
                return False
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(sum(pool.map(attempt, range(12))), 1)

    def test_corrupt_ledger_fails_closed(self):
        ai_budget.DB_PATH.write_text('corrupt')
        with self.assertRaises(BudgetBlocked):
            reserve('s', 10, 1, 1, 20, .03)

    def test_legacy_spend_migrates(self):
        today = datetime.now(timezone.utc).date().isoformat()
        ai_budget.DB_PATH.with_name('.vision_usage.json').write_text(json.dumps({'day':today,'month':today[:7],'day_cost':.06,'month_cost':.09}))
        with self.assertRaises(BudgetBlocked):
            reserve('s', 10, 1, .06, 20, .03)

    @patch('scanner.vision_configured', return_value=True)
    @patch('scanner.analyze_image', return_value=EVIDENCE)
    def test_manual_off_shares_scan_and_no_duplicate(self, analyze, configured):
        rows = [candidate('one'), candidate('two')]
        rows, stats = scanner.analyze_top_deals(rows, 's', 1, 2, 1, 20, .03, .06, 'OFF')
        self.assertEqual(stats['calls_this_scan'], 1)
        self.assertEqual(stats['mode'], 'OFF')
        rows, stats = scanner.analyze_top_deals(rows, 's', 5, 2, 1, 20, .03, .06, 'OFF')
        scanner.analyze_top_deals(rows, 's', 5, 2, 1, 20, .03, .06, 'OFF')
        self.assertEqual(analyze.call_count, 2)
        self.assertEqual(stats['estimated_scan_cost'], .06)

    @patch('scanner.vision_configured', return_value=True)
    @patch('scanner.analyze_image', side_effect=TimeoutError)
    def test_failure_counts_and_skips_retry(self, analyze, configured):
        rows = [candidate()]
        rows, stats = scanner.analyze_top_deals(rows, 's')
        self.assertEqual(stats['estimated_scan_cost'], .03)
        scanner.analyze_top_deals(rows, 's')
        self.assertEqual(analyze.call_count, 1)

    @patch('scanner.vision_configured', return_value=True)
    @patch('scanner.analyze_image', return_value=EVIDENCE)
    def test_plate_never_paid_candidate(self, analyze, configured):
        scanner.analyze_top_deals([candidate(title='EPNS sterling 420g')], 's')
        analyze.assert_not_called()

    @patch('scanner.vision_configured', return_value=True)
    @patch('scanner.analyze_image', return_value=EVIDENCE)
    def test_automatic_then_manual_budget(self, analyze, configured):
        raw = {'itemId':'x','title':'Sterling spoons 420g','price':{'value':'25','currency':'USD'},
               'shippingOptions':[{'shippingCost':{'value':'5','currency':'USD'}}], 'image':{'imageUrl':'https://example.com/x.jpg'}}
        client = Mock(configured=True)
        client.search.return_value = [raw, raw | {'itemId':'y'}]
        with patch('scanner.EbayClient', return_value=client):
            rows = scanner.scan(50, ['q','duplicate q'], vision_mode='SELECTIVE', max_vision_items=1, scan_id='s')
        self.assertEqual(len(rows), 2)
        scanner.analyze_top_deals(rows, 's', max_vision_items=1)
        self.assertEqual(analyze.call_count, 1)


class ConnectorTests(unittest.TestCase):
    @patch('ebay_client.requests.get')
    @patch('ebay_client.requests.post')
    def test_live_request_contract(self, post, get):
        post.return_value.json.return_value = {'access_token':'test-token','expires_in':7200}
        get.return_value.json.return_value = {'itemSummaries':[{'itemId':'x'}]}
        client = EbayClient('test-id','test-secret')
        self.assertEqual(client.search('sterling')[0]['itemId'], 'x')
        self.assertEqual(post.call_args.kwargs['data']['grant_type'], 'client_credentials')
        self.assertEqual(get.call_args.kwargs['params']['fieldgroups'], 'EXTENDED')

    @patch.dict(os.environ, {'OPENAI_API_KEY':'test-only'})
    @patch('image_analyzer.requests.post')
    def test_photo_response_validation(self, post):
        post.return_value.json.return_value = {'output_text':json.dumps(EVIDENCE | {'visual_confidence':150,'likely_purity':5,'estimated_weight_low_g':-12})}
        result = analyze_image(image_url='https://example.com/photo.jpg')
        self.assertEqual(result['visual_confidence'], 100)
        self.assertIsNone(result['likely_purity'])
        self.assertIsNone(result['estimated_weight_low_g'])
        self.assertEqual(post.call_args.kwargs['json']['input'][0]['content'][1]['type'], 'input_image')


class AppTests(IsolatedBudget):
    # Inherit the isolated budget ledger; UI exercises actual Streamlit reruns.
    @patch.dict(os.environ, {'EBAY_CLIENT_ID':'','EBAY_CLIENT_SECRET':'','OPENAI_API_KEY':'','METALS_DEV_API_KEY':''})
    def test_demo_and_calculator(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(Path(__file__).resolve().with_name('app.py')), default_timeout=20).run()
        self.assertFalse(at.exception)
        at.button(key='scan').click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.metric[0].value, '4')
        self.assertIn('🔥 ALERT', at.table[0].value['Deal'].tolist())
        self.assertEqual(at.table[0].value['Hidden Sterling'].tolist(), ['—']*4)
        at.selectbox(key='inspect').select('demo2').run()
        self.assertFalse(at.exception)
        self.assertTrue(any('silverplate' in w.value for w in at.warning))
        at.button(key='calculate').click().run()
        self.assertFalse(at.exception)

    @patch.dict(os.environ, {'EBAY_CLIENT_ID':'','EBAY_CLIENT_SECRET':'','OPENAI_API_KEY':'test-only','METALS_DEV_API_KEY':''})
    @patch('scanner.analyze_image', return_value=EVIDENCE)
    def test_ui_manual_off_budget_and_rerun(self, analyze):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(Path(__file__).resolve().with_name('app.py')), default_timeout=20)
        for key, value in dict(rows=[candidate()], scan_complete=True, scan_id='ui', vision_stats={}).items():
            at.session_state[key] = value
        at.run()
        self.assertFalse(at.exception)
        self.assertEqual(at.selectbox(key='vision_mode').value, 'OFF')
        self.assertFalse(at.button(key='analyze_top').disabled)
        at.number_input(key='daily_budget').set_value(0.0).run()
        at.button(key='analyze_top').click().run()
        self.assertFalse(at.exception)
        analyze.assert_not_called()
        at.number_input(key='daily_budget').set_value(1.0).run()
        at.button(key='analyze_top').click().run()
        self.assertFalse(at.exception)
        self.assertEqual(analyze.call_count, 1)
        self.assertEqual(at.metric[3].value, '$0.030')
        self.assertTrue(at.button(key='analyze_top').disabled)
        at.number_input(key='spot').set_value(100.0).run()
        self.assertEqual(at.session_state['rows'][0]['silver_spot_used'], 50)


if __name__ == '__main__':
    unittest.main(verbosity=2)
