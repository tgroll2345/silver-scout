from __future__ import annotations
import os
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from silver_engine import estimate_listing
from ebay_client import EbayClient
from scanner import scan
from spot_price import get_silver_spot_from_metals_dev
from image_analyzer import analyze_image, configured as vision_configured

load_dotenv()
st.set_page_config(page_title="Silver Scout V2", page_icon="🥈", layout="wide")
st.title("🥈 Silver Scout V2")
st.caption("Find underpriced silver — including listings whose photos reveal more than the seller's description.")

live_spot = get_silver_spot_from_metals_dev()
default_spot = live_spot or float(os.getenv("SILVER_SPOT", "50"))

with st.sidebar:
    st.header("Deal assumptions")
    spot = st.number_input("Silver spot ($/troy oz)", min_value=1.0, value=float(default_spot), step=0.25)
    tax_rate = st.number_input("Estimated sales tax %", min_value=0.0, max_value=15.0, value=0.0, step=0.1) / 100
    refining = st.slider("Realization after refining/selling", 0.70, 1.00, 0.92, 0.01)
    min_profit = st.number_input("Minimum profit alert ($)", value=float(os.getenv("MIN_PROFIT_USD", "75")), step=10.0)
    min_margin = st.number_input("Minimum margin alert (%)", value=float(os.getenv("MIN_MARGIN_PCT", "35")), step=5.0)
    st.divider()
    st.header("Photo intelligence")
    vision_mode = st.selectbox(
        "Paid image analysis mode",
        ["OFF", "SELECTIVE", "AGGRESSIVE"],
        index=0,
        disabled=not vision_configured(),
        help="OFF makes no automatic paid vision calls. SELECTIVE checks only ambiguous/promising listings. AGGRESSIVE checks a broader set."
    )
    max_vision = st.number_input("Max image analyses per scan", min_value=1, max_value=100, value=10, step=1, disabled=(vision_mode == "OFF"))
    daily_budget = st.number_input("Daily AI budget ($)", min_value=0.0, value=1.00, step=0.25, disabled=(vision_mode == "OFF"))
    monthly_budget = st.number_input("Monthly AI budget ($)", min_value=0.0, value=20.00, step=1.0, disabled=(vision_mode == "OFF"))
    est_cost = st.number_input("Estimated cost per image analysis ($)", min_value=0.001, value=float(os.getenv("EST_VISION_COST_USD", "0.03")), step=0.005, format="%.3f", disabled=(vision_mode == "OFF"), help="A safety estimate used for Silver Scout's local budget cap; actual provider billing can vary by model/image/token usage.")
    if not vision_configured(): st.caption("Add OPENAI_API_KEY to .env to enable automatic image analysis.")
    st.caption("Manual Photo Lab analysis remains available even when automatic analysis is OFF.")

client = EbayClient()
mode = "Live eBay" if client.configured else "Demo"
st.info(f"Mode: **{mode}**. " + ("eBay credentials detected." if client.configured else "Waiting for eBay credentials — Demo Mode remains available."))

DEMO = [
    {"item_id":"demo1","title":"Estate lot 12 sterling silver spoons 420 grams","description":"Marked STERLING on reverse. Total weight 420 grams.","price":180,"shipping":12,"url":"","image":"","condition":"Used"},
    {"item_id":"demo2","title":"Vintage silverware set 1847 Rogers Bros","description":"Silver plated flatware, 48 pieces.","price":85,"shipping":18,"url":"","image":"","condition":"Used"},
    {"item_id":"demo3","title":"6 Gorham sterling teaspoons 225g estate find","description":"Each spoon marked Gorham Sterling. Combined weight 225 g.","price":145,"shipping":9,"url":"","image":"","condition":"Used"},
    {"item_id":"demo4","title":"Old silver spoons from estate - untested","description":"Found in estate drawer. Please see photos for markings.","price":55,"shipping":8,"url":"","image":"","condition":"Used"},
]

tab1, tab2, tab3, tab4 = st.tabs(["Scanner", "Photo lab", "Single-item calculator", "Scoring"])
with tab1:
    c1,c2=st.columns([2,1])
    with c1:
        queries_raw=st.text_area("Search phrases (one per line)", value="sterling silver flatware lot\nold silverware estate\nvintage silver utensils\nantique spoons lot\nestate flatware\nold serving spoons\ncoin silver spoons\n800 silver flatware", height=180)
    with c2:
        limit_each=st.number_input("Results per phrase", min_value=5,max_value=100,value=25,step=5)
        run=st.button("Scan now", type="primary", use_container_width=True)
    if run:
        if client.configured:
            try:
                with st.spinner("Scanning and ranking listings..."):
                    rows=scan(spot,[x.strip() for x in queries_raw.splitlines() if x.strip()],int(limit_each),tax_rate,refining,vision_mode,int(max_vision),float(daily_budget),float(monthly_budget),float(est_cost))
            except Exception as e:
                st.error(f"Live scan failed: {e}"); rows=[]
        else:
            rows=[]
            for item in DEMO:
                est=estimate_listing(item["title"],item["description"],item["price"],item["shipping"],spot,tax_rate,refining)
                rows.append(item|est.dict()|{"hidden_sterling_score":0,"image_evidence":None})
            rows.sort(key=lambda x:x["score"],reverse=True)
        st.session_state["rows"]=rows
        stats = next((r.get("_vision_stats") for r in rows if r.get("_vision_stats")), None)
        if stats: st.session_state["vision_stats"] = stats
    rows=st.session_state.get("rows",[])
    if rows:
        stats=st.session_state.get("vision_stats")
        if stats:
            a,b,c=st.columns(3)
            a.metric("Images analyzed this scan", stats.get("calls_this_scan",0))
            b.metric("Estimated AI cost this scan", f'${stats.get("estimated_scan_cost",0):.2f}')
            c.metric("Budget status", stats.get("budget_status","OK"))
        df=pd.DataFrame([{k:v for k,v in r.items() if k != "_vision_stats"} for r in rows])
        df["alert"]=(df["est_profit"].fillna(-1)>=min_profit)&(df["margin_pct"].fillna(-1)>=min_margin)
        cols=[c for c in ["alert","hidden_sterling_score","score","confidence","title","total_cost","conservative_value","est_profit","margin_pct","purity","estimated_gross_grams","url"] if c in df.columns]
        st.dataframe(df[cols],use_container_width=True,hide_index=True,column_config={"url":st.column_config.LinkColumn("Listing")})
        idx=st.selectbox("Inspect candidate", range(len(rows)), format_func=lambda i:f'{rows[i].get("hidden_sterling_score",0)}/100 hidden • {rows[i]["score"]}/100 deal — {rows[i]["title"][:85]}')
        r=rows[idx]
        a,b,c,d=st.columns(4)
        a.metric("All-in cost",f'${r["total_cost"]:,.2f}')
        b.metric("Conservative value","Unknown" if r["conservative_value"] is None else f'${r["conservative_value"]:,.2f}')
        c.metric("Est. profit","Unknown" if r["est_profit"] is None else f'${r["est_profit"]:,.2f}')
        d.metric("Hidden Sterling",f'{r.get("hidden_sterling_score",0)}/100')
        if r.get("image"): st.image(r["image"], width=420)
        for x in r["reasons"]: st.write("✅",x)
        for x in r["risks"]: st.write("⚠️",x)
        if r.get("image_evidence"): st.expander("AI photo evidence").json(r["image_evidence"])
        if r.get("url"): st.link_button("Open eBay listing",r["url"])

with tab2:
    st.subheader("Photo lab")
    st.write("Upload a listing photo to test hallmark/piece recognition before eBay live access is approved.")
    up=st.file_uploader("Listing photo", type=["jpg","jpeg","png","webp"])
    if up:
        st.image(up, width=500)
        if st.button("Analyze photo", type="primary"):
            if not vision_configured(): st.error("Add OPENAI_API_KEY to .env first.")
            else:
                try:
                    with st.spinner("Inspecting hallmarks and construction..."):
                        ev=analyze_image(image_bytes=up.getvalue(), mime_type=up.type or "image/jpeg")
                    st.json(ev)
                except Exception as e: st.error(str(e))

with tab3:
    title=st.text_input("Title","Estate sterling spoon lot 315 grams")
    desc=st.text_area("Description","Marked STERLING. Total weight 315 g.")
    a,b=st.columns(2); price=a.number_input("Price ($)",min_value=0.0,value=120.0); shipping=b.number_input("Shipping ($)",min_value=0.0,value=12.0)
    if st.button("Calculate value"):
        st.json(estimate_listing(title,desc,price,shipping,spot,tax_rate,refining).dict())

with tab4:
    st.markdown("""
**V2 adds a second signal: Hidden Sterling.** Text scoring and photo scoring remain separate so a visually tempting object cannot override explicit seller language such as EPNS or silverplate.

- Photo analysis looks for readable hallmarks, likely purity, plate indicators, weighted/hollow construction, knives/steel blades, maker clues, piece count and piece types.
- If no seller weight exists, V2 may use only the **low end** of a high-confidence visual weight range, and marks that value as estimated.
- **OFF:** no automatic paid image analysis. **SELECTIVE:** only promising/ambiguous listings. **AGGRESSIVE:** a broader candidate pool.
- Per-scan limits plus local daily/monthly budget caps stop new automatic image calls when the configured allowance is reached. Actual provider billing may differ from the local estimate.
- Seller-provided solid evidence remains stronger than image inference.
""")
