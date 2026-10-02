"""Formatting kept separate from scoring; seller text is never trusted markup."""
import re
from urllib.parse import urlparse, quote
import pandas as pd
import streamlit as st
from scanner import is_alert


def money(value):
    return 'Unknown' if value is None else f'${value:,.2f}'


def percent(value):
    return '—' if value is None else f'{value:.1f}%'


def ebay_url(value):
    parsed = urlparse(value or '')
    host = (parsed.hostname or '').lower()
    if parsed.scheme == 'https' and (host == 'ebay.com' or host.endswith('.ebay.com')) and not parsed.username:
        return quote(value, safe=':/?=&%+#@;,-_.~')
    return ''


def title_link(row):
    title = row['title']
    short = title if len(title) <= 65 else title[:62] + '…'
    label = re.sub(r'([\\`*_{}\[\]()<>#+.!|~-])', r'\\\1', short.replace('\n', ' '))
    url = ebay_url(row.get('url'))
    return f'[{label}]({url})' if url else label


def table_data(rows, min_profit, min_margin):
    return pd.DataFrame([{
        'Deal': '🔥 ALERT' if is_alert(r, min_profit, min_margin) else 'WATCH',
        'Listing ↗': title_link(r),
        'All-in¹': money(r['total_cost']) if r.get('valuation_eligible', True) else 'Unverified',
        'Metal value²': money(r['conservative_value']),
        'Profit': money(r['est_profit']),
        'ROI': percent(r['margin_pct']),
        'Discount': percent(r.get('discount_pct')),
        'Hidden Sterling': f"{r.get('hidden_sterling_score', 0)}/100" if r.get('image_evidence') and 'error' not in r['image_evidence'] else '—',
        'Confidence': f"{r['confidence']}/100",
    } for r in rows])


def explain(row, min_profit, min_margin):
    alert = is_alert(row, min_profit, min_margin)
    with st.expander('Explain this deal — ' + ('🔥 ALERT' if alert else 'WATCH'), expanded=True):
        st.subheader(row['title'])
        with st.container(horizontal=True):
            st.metric('All-in price', money(row['total_cost']) if row.get('valuation_eligible', True) else 'Unverified', border=True)
            st.metric('Conservative metal value', money(row['conservative_value']), border=True)
            st.metric('Projected profit', money(row['est_profit']), border=True)
        st.table({
            'Detected weight': f"{row['estimated_gross_grams']:,.2f} g" if row['estimated_gross_grams'] is not None else 'Unknown',
            'Weight evidence': row.get('weight_source', 'Unknown'),
            'Detected purity': f"{row['purity']:.3f}" if row['purity'] is not None else 'Unverified / plate text excludes valuation',
            'Silver spot used': money(row['silver_spot_used']) + ' / troy oz',
            'Recoverable fraction': percent(row['recoverable_fraction'] * 100),
            'Realization after selling/refining': percent(row['realization_used'] * 100),
            'Price + shipping + tax': f"{money(row['price'])} + {money(row['shipping'])} + {percent(row['tax_rate_used'] * 100)} tax" if row.get('valuation_eligible', True) else 'Verify listing currency, shipping and checkout tax',
            'Margin / discount to value': percent(row['margin_pct']) + ' / ' + percent(row.get('discount_pct')),
        }, border='horizontal')
        st.markdown('**Why it was flagged**' if alert else '**Why it is on watch**')
        if alert:
            st.write(f"Projected profit meets ${min_profit:,.2f}; margin meets {min_margin:.1f}%.")
        else:
            st.write('Profit/margin thresholds are not both met, valuation inputs are unverified, or construction/photo weight assumptions require review.')
        for reason in row['reasons']:
            st.text('✓ ' + reason)
        for warning in row['risks']:
            st.warning(warning)
        st.caption('Value = gross grams ÷ 31.1034768 × purity × recoverable fraction × spot × realization. Profit = value − all-in cost. Construction recovery fractions are screening assumptions, not measured silver content.')
        if row.get('image'):
            st.image(row['image'], width=320)
        if row.get('image_evidence'):
            with st.expander('Photo evidence and uncertainty'):
                st.json(row['image_evidence'])
        url = ebay_url(row.get('url'))
        if url:
            st.link_button('View on eBay', url)
