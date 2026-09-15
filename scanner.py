from __future__ import annotations
from uuid import uuid4
from dotenv import load_dotenv
from ebay_client import EbayClient, normalize_item
from silver_engine import estimate_listing, explicit_plate, detect_purity
from image_analyzer import analyze_image, configured as vision_configured
from ai_budget import reserve, snapshot, BudgetBlocked

load_dotenv()
DEFAULT_QUERIES = ['sterling silver flatware lot', 'old silver spoons estate', 'coin silver spoons', '800 silver flatware']


def is_alert(row, min_profit=75, min_margin=35):
    return (not explicit_plate(row.get('title', '') + ' ' + row.get('description', ''))
            and row.get('valuation_eligible', True)
            and row.get('est_profit') is not None and row.get('margin_pct') is not None
            and row['est_profit'] >= min_profit and row['margin_pct'] >= min_margin)


def rank_key(row):
    profit = row.get('est_profit')
    return (row.get('valuation_eligible', True), row.get('score', 0), profit if profit is not None else -1e12,
            row.get('hidden_sterling_score', 0))


def photo_candidates(rows):
    return sorted([r for r in rows if r.get('image') and not r.get('_photo_attempted')
                   and r.get('image_evidence') is None
                   and not explicit_plate(r.get('title', '') + ' ' + r.get('description', ''))], key=rank_key, reverse=True)


def apply_estimate(row, spot, tax_rate, refining_discount, evidence=None):
    row.update(estimate_listing(row['title'], row['description'], row['price'], row['shipping'],
                               spot, tax_rate, refining_discount, image_evidence=evidence).dict())
    if not row.get('valuation_eligible', True):
        row.update(conservative_value=None, melt_value=None, est_profit=None, margin_pct=None, discount_pct=None)
        row['risks'].append('Price/shipping is missing or not in USD; verify full delivered cost on eBay')
    if row.get('description_incomplete'):
        row['risks'].append('Search summary only: read full seller description for plate terms and construction before buying')


def analyze_top_deals(rows, scan_id, top_n=5, max_vision_items=10, daily_budget=1.0,
                      monthly_budget=20.0, estimated_cost_per_image=0.03, scan_budget=0.30,
                      vision_mode='OFF'):
    status = 'Ready'
    if not vision_configured():
        return rows, {'mode': vision_mode, 'budget_status': 'OpenAI key is not configured'}
    candidates = photo_candidates(rows)[:int(top_n)]
    for row in candidates:
        try:
            reserve(scan_id, max_vision_items, scan_budget, daily_budget, monthly_budget, estimated_cost_per_image)
        except BudgetBlocked as exc:
            status = str(exc)
            break
        row['_photo_attempted'] = True
        try:
            ev = analyze_image(image_url=row['image'])
            row['image_evidence'] = ev
            apply_estimate(row, row['silver_spot_used'], row['tax_rate_used'], row['realization_used'], ev)
            text = row['title'] + ' ' + row['description']
            unidentified = detect_purity(text)[0] is None
            hidden = round(ev.get('silver_likelihood', 0)*.55 + ev.get('visual_confidence', 0)*.35
                           - ev.get('plated_likelihood', 0)*.45 + (15 if unidentified else 0))
            row['hidden_sterling_score'] = 0 if explicit_plate(text) else max(0, min(100, hidden))
        except Exception:
            row['image_evidence'] = {'error': 'Photo analysis failed. Estimated cost retained because the request may have been billed.'}
            status = 'Some photo analyses failed; reserved estimates still count'
    try:
        stats = snapshot(scan_id)
    except Exception:
        stats = {}
        status = 'Budget ledger unavailable; further AI calls will be blocked'
    stats.update(mode=vision_mode, budget_status=status, scan_id=scan_id,
                 images_analyzed=sum(bool(r.get('image_evidence')) and 'error' not in r['image_evidence'] for r in rows))
    return sorted(rows, key=rank_key, reverse=True), stats


def scan(spot: float, queries=None, limit_each=30, tax_rate=0.0, refining_discount=0.92,
         vision_mode='OFF', max_vision_items=10, daily_budget=1.0, monthly_budget=20.0,
         estimated_cost_per_image=0.03, scan_budget=0.30, scan_id=None):
    client = EbayClient()
    if not client.configured:
        raise RuntimeError('Configure eBay credentials in Streamlit Secrets or .env')
    seen, out = set(), []
    scan_id = scan_id or uuid4().hex
    for q in queries or DEFAULT_QUERIES:
        for raw in client.search(q, limit=limit_each):
            item = normalize_item(raw)
            if not item['item_id'] or item['item_id'] in seen:
                continue
            seen.add(item['item_id'])
            apply_estimate(item, spot, tax_rate, refining_discount)
            out.append(item | {'image_evidence': None, 'hidden_sterling_score': 0})
    out.sort(key=rank_key, reverse=True)
    stats = {'mode': vision_mode, 'budget_status': 'Automatic analysis OFF', 'calls_this_scan': 0,
             'estimated_scan_cost': 0, 'scan_id': scan_id, 'images_analyzed': 0}
    if vision_mode != 'OFF':
        candidates = out if vision_mode == 'AGGRESSIVE' else [r for r in out if r.get('purity') is None or r.get('estimated_gross_grams') is None or r.get('score', 0) >= 50]
        _, stats = analyze_top_deals(candidates, scan_id, max_vision_items, max_vision_items,
                                     daily_budget, monthly_budget, estimated_cost_per_image, scan_budget, vision_mode)
        out.sort(key=rank_key, reverse=True)
    if out:
        out[0]['_vision_stats'] = stats
    return out
