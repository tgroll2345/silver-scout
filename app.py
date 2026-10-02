from __future__ import annotations
import os
from pathlib import Path
from uuid import uuid4
import streamlit as st
import pandas as pd
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name('.env'))
# Explicit support for Cloud Secrets as well as local .env. Never export unrelated secrets.
try:
    for name in ('EBAY_CLIENT_ID', 'EBAY_CLIENT_SECRET', 'EBAY_MARKETPLACE_ID', 'OPENAI_API_KEY',
                 'OPENAI_VISION_MODEL', 'METALS_DEV_API_KEY', 'AI_USAGE_DB', 'SILVER_SPOT',
                 'MIN_PROFIT_USD', 'MIN_MARGIN_PCT', 'EST_VISION_COST_USD'):
        if name in st.secrets:
            os.environ[name] = str(st.secrets[name])
except FileNotFoundError:
    pass

from silver_engine import estimate_listing
from ebay_client import EbayClient
from scanner import scan, analyze_top_deals, photo_candidates, is_alert, rank_key, apply_estimate
from spot_price import get_silver_spot_from_metals_dev
from image_analyzer import analyze_image, configured as vision_configured
from ai_budget import reserve, BudgetBlocked
from results_ui import table_data, explain

st.set_page_config(page_title='Silver Scout V2.2.2', page_icon='🥈', layout='wide')
st.title('🥈 Silver Scout V2.2.2')
st.caption('Version 2.2.2 · Compare the cost. Check the silver evidence. Understand the deal.')

@st.cache_data(ttl=900, max_entries=2)
def live_spot_value():
    return get_silver_spot_from_metals_dev()

live_spot = live_spot_value()
default_spot = live_spot or float(os.getenv('SILVER_SPOT', '50'))
with st.sidebar:
    st.header('Deal assumptions')
    spot = st.number_input('Silver spot ($/troy oz)', min_value=1.0, value=float(default_spot), step=0.25, key='spot')
    st.caption('Live provider value (cached up to 15 minutes).' if live_spot else 'Manual spot assumption — verify and update before scanning.')
    tax_rate = st.number_input('Estimated sales tax %', min_value=0.0, max_value=15.0, value=0.0, step=0.1) / 100
    refining = st.slider('Realization after refining/selling', 0.70, 1.00, 0.92, 0.01)
    min_profit = st.number_input('Minimum profit alert ($)', min_value=0.0, value=float(os.getenv('MIN_PROFIT_USD', '75')), step=10.0)
    min_margin = st.number_input('Minimum margin alert (%)', min_value=0.0, value=float(os.getenv('MIN_MARGIN_PCT', '35')), step=5.0)
    st.divider()
    st.header('Photo intelligence')
    vision_mode = st.selectbox('Automatic image AI', ['OFF', 'SELECTIVE', 'AGGRESSIVE'], key='vision_mode', disabled=not vision_configured())
    max_vision = st.number_input('Max image analyses per scan', min_value=1, max_value=100, value=10, key='max_vision')
    scan_budget = st.number_input('Per-scan AI budget ($)', min_value=0.0, value=0.30, step=0.05, key='scan_budget')
    daily_budget = st.number_input('Daily AI budget ($)', min_value=0.0, value=1.0, step=0.25, key='daily_budget')
    monthly_budget = st.number_input('Monthly AI budget ($)', min_value=0.0, value=20.0, step=1.0, key='monthly_budget')
    est_cost = st.number_input('Estimated cost per analysis ($)', min_value=0.001, value=float(os.getenv('EST_VISION_COST_USD', '0.03')), step=0.005, format='%.3f', key='est_cost')
    st.caption('OFF stops automatic calls. The top-deals button and Photo Lab still work within these caps. A $0 cap blocks paid analysis. Estimates include failed requests; actual OpenAI charges may differ.')
    if not vision_configured():
        st.caption('Add OPENAI_API_KEY in Streamlit Secrets or local .env to enable photos.')

client = EbayClient()
st.info('Live eBay • credentials detected' if client.configured else 'Demo mode • sample listings, no live eBay calls')
DEMO = [
    {'item_id':'demo1','title':'Estate lot 12 sterling silver spoons 420 grams','description':'Marked STERLING on reverse. Total weight 420 grams.','price':180,'shipping':12,'url':'','image':''},
    {'item_id':'demo2','title':'Vintage silverware set 1847 Rogers Bros','description':'Silver plated flatware, 48 pieces.','price':85,'shipping':18,'url':'','image':''},
    {'item_id':'demo3','title':'6 Gorham sterling teaspoons 225g estate find','description':'Each spoon marked Gorham Sterling. Combined weight 225 g.','price':145,'shipping':9,'url':'','image':''},
    {'item_id':'demo4','title':'Old silver spoons from estate - untested','description':'Found in estate drawer. Please see photos for markings.','price':55,'shipping':8,'url':'','image':''},
]
tab1, tab2, tab3, tab4, tab5 = st.tabs(['Scanner', 'Photo lab', 'Single-item calculator', 'Scoring', 'Deal journal'])
with tab1:
    with st.expander('Search settings', expanded=not bool(st.session_state.get('rows'))):
        queries = st.text_area('Search phrases (one per line)', 'sterling silver flatware lot\nold silverware estate\nvintage silver utensils\nantique spoons lot\nestate flatware\nold serving spoons\ncoin silver spoons\n800 silver flatware', height=150)
        limit_each = st.number_input('Results per phrase', min_value=5, max_value=100, value=25, step=5)
    if st.button('Scan now', type='primary', key='scan'):
        scan_id = uuid4().hex
        st.session_state.update(scan_id=scan_id, rows=[], vision_stats={}, scan_complete=False)
        try:
            with st.spinner('Scanning and ranking listings…'):
                if client.configured:
                    phrases = [q.strip() for q in queries.splitlines() if q.strip()]
                    if not phrases:
                        raise ValueError('Enter at least one search phrase')
                    rows = scan(spot, phrases, int(limit_each), tax_rate, refining, vision_mode,
                                int(max_vision), daily_budget, monthly_budget, est_cost, scan_budget, scan_id)
                else:
                    rows = [dict(item) for item in DEMO]
                    for row in rows:
                        apply_estimate(row, spot, tax_rate, refining)
                        row.update(hidden_sterling_score=0, image_evidence=None)
                    rows.sort(key=rank_key, reverse=True)
                stats = next((r['_vision_stats'] for r in rows if '_vision_stats' in r), {})
                st.session_state.update(rows=rows, vision_stats=stats, scan_complete=True)
        except Exception as exc:
            st.error(f'Scan could not complete: {exc}')
    rows = st.session_state.get('rows', [])
    if st.session_state.get('scan_complete'):
        stats = st.session_state.get('vision_stats', {})
        with st.container(horizontal=True):
            st.metric('Listings scanned', len(rows), border=True)
            st.metric('Deals flagged', sum(is_alert(r, min_profit, min_margin) for r in rows), border=True)
            st.metric('Image AI mode', vision_mode, border=True)
            st.metric('Estimated AI spend', f"${stats.get('estimated_scan_cost', 0):.3f}", border=True)
        st.caption(f"{stats.get('images_analyzed', 0)} photos analyzed · {stats.get('calls_this_scan', 0)} requests reserved this scan. {stats.get('budget_status', '')}")
        if not rows:
            st.info('No listings returned. Try another search phrase.')
    if rows:
        candidates = photo_candidates(rows)
        with st.container(border=True):
            st.subheader('Take a closer look')
            top_n = st.selectbox('Promising deals to analyze', [1, 3, 5, 10], index=2, key='top_n')
            selected = candidates[:top_n]
            st.caption(f'{len(selected)} eligible photos · up to ${len(selected)*est_cost:.3f} estimated, subject to remaining caps. Already attempted photos and explicit plate listings are skipped.')
            with st.expander('Preview candidates before analyzing'):
                for candidate in selected:
                    st.text(candidate['title'])
                if not selected:
                    st.write('No eligible photos remain in this scan.')
            if st.button('Analyze photos for top deals', key='analyze_top', disabled=not vision_configured() or not candidates):
                with st.spinner('Analyzing promising photos within your budget…'):
                    rows, stats = analyze_top_deals(rows, st.session_state['scan_id'], top_n, int(max_vision),
                                                   daily_budget, monthly_budget, est_cost, scan_budget, vision_mode)
                st.session_state.update(rows=rows, vision_stats=stats)
                st.rerun()
        order = st.selectbox('Sort results', ['Alerts first', 'Highest projected profit', 'Highest confidence', 'Hidden Sterling'], key='sort')
        if order == 'Alerts first':
            ordered = sorted(rows, key=lambda r: (is_alert(r, min_profit, min_margin), rank_key(r)), reverse=True)
        elif order == 'Highest projected profit':
            ordered = sorted(rows, key=lambda r: r['est_profit'] if r['est_profit'] is not None else -1e12, reverse=True)
        elif order == 'Highest confidence':
            ordered = sorted(rows, key=lambda r: r['confidence'], reverse=True)
        else:
            ordered = sorted(rows, key=lambda r: r.get('hidden_sterling_score', 0), reverse=True)
        alert_only = st.checkbox('Show alerts only')
        confidence_floor = st.slider('Minimum confidence', 0, 100, 0)
        max_cost = st.number_input('Maximum delivered cost ($; 0 means no limit)', min_value=0.0, value=0.0)
        ordered = [r for r in ordered if (not alert_only or is_alert(r, min_profit, min_margin))
                   and r['confidence'] >= confidence_floor
                   and (not max_cost or (r.get('valuation_eligible', True) and r['total_cost'] <= max_cost))]
        st.caption(f'{len(ordered)} listings match your filters.')
        if not ordered:
            st.info('No matching listings. Widen the filters.')
        page = st.selectbox('Results page', list(range(1, max(1, (len(ordered)-1)//15 + 1) + 1)), key='page')
        st.table(table_data(ordered[(page-1)*15:page*15], min_profit, min_margin), hide_index=True)
        st.caption('¹ Price + shipping + estimated tax, USD. ² After construction and realization adjustments. Margin = profit ÷ cost; discount = 1 − cost ÷ value. “—” Hidden Sterling means no successful photo analysis. Confidence is a heuristic score, not a probability.')
        st.caption('Scan valuations retain their original spot, tax and realization assumptions. Run a new scan to apply changed assumptions. Alerts use your current profit/margin thresholds.')
        by_id = {r['item_id']: r for r in ordered}
        selected_id = st.selectbox('Inspect candidate', list(by_id), format_func=lambda k: by_id[k]['title'], key='inspect')
        if selected_id:
            explain(by_id[selected_id], min_profit, min_margin)
            if st.button('Save to deal journal'):
                saved = dict(by_id[selected_id])
                saved.update(status='Flagged', actual_purchase=None, actual_proceeds=None, notes='',
                             saved_at=datetime.now(timezone.utc).isoformat())
                st.session_state.setdefault('journal', {})[selected_id] = saved
                st.success('Saved. Open Deal journal to track the outcome.')

with tab2:
    st.subheader('Photo lab')
    st.write('Upload a listing photo to inspect visible markings and construction.')
    st.caption('Uses the same daily/monthly ledger. The per-scan allowance applies across Photo Lab requests in this browser session.')
    st.session_state.setdefault('lab_id', 'lab-' + uuid4().hex)
    up = st.file_uploader('Listing photo', type=['jpg', 'jpeg', 'png', 'webp'])
    if up:
        st.image(up, width=400)
        if st.button('Analyze photo', key='lab_analyze', disabled=not vision_configured()):
            try:
                reserve(st.session_state['lab_id'], int(max_vision), scan_budget, daily_budget, monthly_budget, est_cost)
                with st.spinner('Inspecting hallmarks and construction…'):
                    st.session_state['lab_result'] = analyze_image(image_bytes=up.getvalue(), mime_type=up.type or 'image/jpeg')
            except BudgetBlocked as exc:
                st.warning(str(exc))
            except Exception:
                st.error('Photo analysis failed. Its estimated cost still counts toward the budget.')
        if st.session_state.get('lab_result'):
            st.json(st.session_state['lab_result'])

with tab3:
    title = st.text_input('Title', 'Estate sterling spoon lot 315 grams')
    desc = st.text_area('Description', 'Marked STERLING. Total weight 315 g.')
    price = st.number_input('Price ($)', min_value=0.0, value=120.0)
    shipping = st.number_input('Shipping ($)', min_value=0.0, value=12.0)
    if st.button('Calculate value', key='calculate'):
        st.json(estimate_listing(title, desc, price, shipping, spot, tax_rate, refining).dict())

with tab4:
    st.markdown('''
### How to read a deal
- **🔥 ALERT** meets your profit and ROI thresholds with available valuation inputs, full recovery, and a text-derived weight. **WATCH** needs more evidence or does not meet both thresholds.
- **Hidden Sterling** is a photo-derived screening score. It appears as **—** until a photo is successfully analyzed; it is not the probability that the item is sterling.
- Explicit **silverplate / silver plated / silver-plated / silver plate / EPNS** text excludes solid-silver valuation even if a photo suggests sterling.
- Weight, purity, construction recovery and realization assumptions are shown in each deal explanation. Conflicting weights remain unknown.
- Knives, weighted pieces and hollow handles carry construction warnings and reduced recovery assumptions. These and photo-estimated weights stay on WATCH even when estimated profit meets thresholds. Actual recoverable silver can be lower.
- Live search returns a seller summary, which may omit details. Read the full listing and verify weight, construction, shipping and taxes before buying.
- **OFF** makes no automatic paid calls; **SELECTIVE** checks promising or ambiguous results; **AGGRESSIVE** checks a broader set. The top-deals button works in all modes.
- Every photo request reserves estimated spend first, including failed requests. Automatic and manual requests share the scan limits and daily/monthly caps. A zero-dollar cap stops calls.
- Budgets cap local estimates, not provider invoices. UTC day/month counters persist on this app instance's disk; ephemeral hosting or a redeployment can reset them. Use persistent AI_USAGE_DB storage for continuity.
''')

with tab5:
    st.subheader('Deal journal')
    st.caption('Private to this browser session. Download a backup before leaving; this journal is not stored in a permanent account.')
    journal = st.session_state.setdefault('journal', {})
    if not journal:
        st.info('Inspect a scanner result and select Save to deal journal.')
    else:
        jid = st.selectbox('Saved deal', list(journal), format_func=lambda k: journal[k]['title'])
        deal = journal[jid]
        with st.form('journal_edit'):
            status = st.selectbox('Status', ['Flagged', 'Bought', 'Sold', 'Passed'],
                                 index=['Flagged', 'Bought', 'Sold', 'Passed'].index(deal['status']))
            purchase = st.number_input('Actual total purchase cost ($)', min_value=0.0,
                                       value=float(deal['actual_purchase'] or 0))
            proceeds = st.number_input('Actual net proceeds after fees ($)', min_value=0.0,
                                       value=float(deal['actual_proceeds'] or 0))
            notes = st.text_area('Notes', deal['notes'])
            if st.form_submit_button('Update deal'):
                deal.update(status=status, actual_purchase=purchase, actual_proceeds=proceeds, notes=notes)
        if deal['status'] == 'Sold' and deal['actual_purchase'] is not None and deal['actual_proceeds'] is not None:
            st.metric('Actual profit', f"${deal['actual_proceeds'] - deal['actual_purchase']:,.2f}")
        columns = ['item_id', 'title', 'url', 'status', 'total_cost', 'est_profit',
                   'actual_purchase', 'actual_proceeds', 'notes', 'saved_at']
        records = [{k: row.get(k) for k in columns} for row in journal.values()]
        # Neutralize formula-leading seller text in spreadsheet exports.
        for record in records:
            for key, value in record.items():
                if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
                    record[key] = "'" + value
        data = pd.DataFrame(records)
        st.dataframe(data, hide_index=True)
        st.download_button('Download journal CSV', data.to_csv(index=False).encode('utf-8'),
                           'silver-scout-journal.csv', 'text/csv')
