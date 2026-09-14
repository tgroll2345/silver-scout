from __future__ import annotations
import json, os
from datetime import date
from pathlib import Path
from dotenv import load_dotenv
from ebay_client import EbayClient, normalize_item
from silver_engine import estimate_listing
from image_analyzer import analyze_image, configured as vision_configured

load_dotenv()
USAGE_FILE = Path(__file__).with_name('.vision_usage.json')
DEFAULT_QUERIES = [
    "sterling silver flatware lot", "925 silver flatware", "sterling silver spoons lot",
    "old silver spoons estate", "sterling silverware estate lot", "coin silver spoons",
    "800 silver flatware", "old silverware estate", "vintage silver utensils",
    "antique spoons lot", "estate flatware", "old serving spoons",
]

def _worth_visual_check(row: dict) -> bool:
    text=(row.get('title','')+' '+row.get('description','')).lower()
    vague=any(x in text for x in ['old silver','estate','antique spoon','silverware','flatware','utensil'])
    return bool(row.get('image')) and (row.get('purity') is None or row.get('estimated_gross_grams') is None or vague)

def _aggressive_visual_check(row: dict) -> bool:
    text=(row.get('title','')+' '+row.get('description','')).lower()
    negative=any(x in text for x in ['epns','silver plated','silverplate','silver plate'])
    return bool(row.get('image')) and not negative

def _usage():
    today=date.today().isoformat(); month=today[:7]
    try: d=json.loads(USAGE_FILE.read_text())
    except Exception: d={}
    if d.get('day') != today: d['day']=today; d['day_cost']=0.0; d['day_calls']=0
    if d.get('month') != month: d['month']=month; d['month_cost']=0.0; d['month_calls']=0
    return d

def _save_usage(d):
    try: USAGE_FILE.write_text(json.dumps(d,indent=2))
    except Exception: pass

def scan(spot: float, queries=None, limit_each=30, tax_rate=0.0, refining_discount=0.92,
         vision_mode='OFF', max_vision_items=10, daily_budget=1.0, monthly_budget=20.0,
         estimated_cost_per_image=0.03):
    client=EbayClient()
    if not client.configured: raise RuntimeError('Add EBAY_CLIENT_ID and EBAY_CLIENT_SECRET to .env')
    seen,out=set(),[]
    for q in queries or DEFAULT_QUERIES:
        for raw in client.search(q,limit=limit_each):
            item=normalize_item(raw)
            if not item['item_id'] or item['item_id'] in seen: continue
            seen.add(item['item_id'])
            est=estimate_listing(item['title'],item['description'],item['price'],item['shipping'],spot,tax_rate,refining_discount)
            out.append(item|est.dict()|{'image_evidence':None,'hidden_sterling_score':0})
    out.sort(key=lambda x:(x.get('score',0),-(x.get('total_cost') or 0)),reverse=True)

    calls=0; status='OFF' if vision_mode=='OFF' else 'OK'; usage=_usage()
    if vision_mode!='OFF' and vision_configured():
        predicate=_worth_visual_check if vision_mode=='SELECTIVE' else _aggressive_visual_check
        candidates=[r for r in out if predicate(r)]
        for row in candidates:
            if calls >= max_vision_items: status='Per-scan limit reached'; break
            if daily_budget > 0 and usage.get('day_cost',0)+estimated_cost_per_image > daily_budget: status='Daily budget reached'; break
            if monthly_budget > 0 and usage.get('month_cost',0)+estimated_cost_per_image > monthly_budget: status='Monthly budget reached'; break
            try:
                ev=analyze_image(image_url=row['image']); calls+=1
                usage['day_calls']=usage.get('day_calls',0)+1; usage['month_calls']=usage.get('month_calls',0)+1
                usage['day_cost']=round(usage.get('day_cost',0)+estimated_cost_per_image,6)
                usage['month_cost']=round(usage.get('month_cost',0)+estimated_cost_per_image,6); _save_usage(usage)
                row['image_evidence']=ev
                est=estimate_listing(row['title'],row['description'],row['price'],row['shipping'],spot,tax_rate,refining_discount,image_evidence=ev)
                row.update(est.dict())
                visual=int(ev.get('visual_confidence') or 0); silver=int(ev.get('silver_likelihood') or 0); plated=int(ev.get('plated_likelihood') or 0)
                text_low=(row.get('title','')+' '+row.get('description','')).lower()
                seller_did_not_identify=not any(k in text_low for k in ['sterling','925','900','835','830','800','coin silver'])
                row['hidden_sterling_score']=max(0,min(100,round((silver*.55+visual*.35-plated*.45)+(15 if seller_did_not_identify else 0))))
            except Exception as e: row['image_evidence']={'error':str(e)}
    stats={'calls_this_scan':calls,'estimated_scan_cost':round(calls*estimated_cost_per_image,4),'estimated_today_cost':usage.get('day_cost',0),'estimated_month_cost':usage.get('month_cost',0),'budget_status':status,'mode':vision_mode}
    if out: out[0]['_vision_stats']=stats
    return sorted(out,key=lambda x:(x.get('hidden_sterling_score',0),x.get('score',0),x.get('est_profit') or -10**9),reverse=True)
