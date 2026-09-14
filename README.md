# Silver Scout V2

Silver Scout ranks potentially underpriced silver listings using conservative melt-value math plus optional AI photo analysis.

## Launch on Windows
1. Open Command Prompt in this folder.
2. `py -m pip install -r requirements.txt`
3. Copy `.env.example` to `.env`.
4. `py -m streamlit run app.py`

## Demo mode
Works without eBay keys. The Photo Lab also works before eBay approval if you add an OpenAI API key.

## Live eBay
Add `EBAY_CLIENT_ID` and `EBAY_CLIENT_SECRET` to `.env` after eBay approves your developer account.

## Photo intelligence
Add `OPENAI_API_KEY` to `.env`, restart the app, then use **Photo lab** or enable **Analyze promising listing photos** in the sidebar. API usage may incur separate charges. Keep the per-scan photo limit low while testing.

V2 image analysis is deliberately conservative and should be treated as screening evidence, not authentication or assay.
