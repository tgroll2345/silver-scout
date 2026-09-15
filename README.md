# Silver Scout V2.2

An update of the recovered `silver_scout_v2_1 (1).zip` project. The application entry point is still **app.py**. Production eBay OAuth/Browse scanning, the OpenAI Responses photo-analysis request, Demo mode, Photo Lab and the single-item calculator are retained.

## Update your existing GitHub / Streamlit app

1. Download and extract `silver_scout_v2_2.zip` on your computer.
2. Open your existing Silver Scout GitHub repository. Keep a copy of its current files or note the current commit so you can roll back.
3. Upload **the extracted files and folders**, including the updated `requirements.txt`, to the same repository folder that currently contains `app.py`. Do not upload the ZIP itself or place the files inside another `silver_scout_v2_2` folder. The ZIP has app.py at its root to make this easier.
4. Commit the update. Keep your current Streamlit app linked to the same repository and branch, with main file path **app.py**. Do not create a replacement app.
5. Keep your existing Streamlit Secrets. No new eBay or OpenAI keys are required. Wait for Streamlit to install requirements and reload, or reboot from its management menu if necessary.
6. Confirm the page says **Silver Scout V2.2**. Leave automatic Image AI **OFF**, enter/verify the current silver spot, and run a small live search. Check an eBay title link and the deal explanation.
7. To test paid photos, set nonzero caps and choose **1** promising deal. Click **Analyze photos for top deals**. Verify the request count, spend estimate and evidence. Automatic Image AI can remain OFF.

Keep `.env`, `.streamlit/secrets.toml`, `.ai_usage.sqlite3` and `.vision_usage.json` out of GitHub. The package includes safe example files only. `.gitignore` cannot remove secrets already committed.

**Runtime:** Python 3.10 or newer; Python 3.12 was used for testing. Streamlit is pinned to 1.63.0, the version used for the UI tests. Existing package requirements must be updated along with the Python files.

## What changed

- Clear **🔥 ALERT / WATCH** text replaces disabled Boolean checkboxes.
- Summary: unique listings scanned, deals flagged, current automatic Image AI mode and estimated spend for the current scan.
- Compact, paginated comparison table prioritizes clickable eBay titles, all-in price, conservative metal value, projected profit, margin, discount, Hidden Sterling and confidence.
- Sort by alerts, profit, confidence or Hidden Sterling; inspect any candidate in the selectable, expandable explanation panel.
- Every explanation records detected weight and its source, purity, spot used, recoverable fraction, realization, cost, projected profit, reasons and construction warnings.
- Manual **Analyze photos for top deals** works with automatic Image AI OFF. It previews candidates, selects the highest-ranked eligible remaining photos and skips attempted photos or explicit plate listings. The count requested is an upper limit; budgets may allow fewer.
- Automatic calls, top-deal calls and Photo Lab all reserve budget before contacting OpenAI. Failed requests count because they may still be billed.
- A $0 budget now **blocks calls**. It no longer means unlimited.

## Reading results

**ALERT** means projected profit and margin meet the sidebar thresholds with available pricing inputs. It is a screening result, not an instruction to buy. WATCH means the thresholds are not both met or a necessary input is unknown.

- All-in price = asking price + shipping + estimated sales tax on that subtotal.
- Conservative value = grams / 31.1034768 × purity × recoverable fraction × silver spot per troy oz × realization factor.
- Profit = conservative value − all-in price.
- Margin = profit / all-in price × 100. This is return on cost, not profit divided by proceeds.
- Discount = (1 − all-in price / conservative value) × 100.
- Confidence is a heuristic score out of 100, not an independently calibrated probability.
- Hidden Sterling is shown as **84/100**, for example. **—** means no successful photo analysis; it does not mean the item has zero silver likelihood. The score is photo-derived and not an authentication result.

All valuations retain the spot, tax and realization assumptions used at scan time. Changing those controls requires a new scan. Changing alert thresholds immediately updates the flags.

Explicit silverplate, silver plated, silver-plated, silver plate, EPNS and other recognized base-metal wording overrides visual sterling evidence. Such listings get no solid-silver valuation or profit alert. Photo-derived weight uses only the low end of an eligible range. Conflicting text weights remain unknown rather than choosing the largest number.

Weighted construction, hollow handles and knives reduce assumed recoverable weight and generate warnings. These fractions are conservative screening assumptions, not measured recoverable metal. Actual silver content may be lower. Verify the weight excluding steel blades, filler, packaging and cases.

The preserved eBay search integration provides titles and available short descriptions, not guaranteed full seller descriptions. The panel explicitly warns about that limit: read the complete listing before buying. Explicit plate text in available data always wins; text absent from the search response cannot be checked. Listings with unknown shipping or non-USD price/shipping are marked **Unverified**, with metal value/profit suppressed until the full delivered cost can be checked. No currency conversion is performed.

## AI modes and budget behavior

- **OFF:** no automatic calls during scanning. Manual top-deal analysis and Photo Lab remain available.
- **SELECTIVE:** checks ambiguous or promising candidates.
- **AGGRESSIVE:** checks a broader candidate pool.
- Both automatic and manual top-deal calls share the current scan's request count and dollar allowance, even over multiple button clicks.
- Photo Lab has a separate per-session request/dollar allowance using the same sidebar limits, and shares daily/monthly spend with the scanner. Its requests do not appear in the scanner's current-scan summary.
- Day and month limits use **UTC** and share one SQLite ledger across sessions/processes using the same file.
- Every attempt reserves the configured estimated cost first. There are no automatic retries or refunds. A failed photo is skipped on subsequent clicks in the same scan; a new scan may attempt it again within remaining budgets.
- If the ledger is corrupt or cannot be saved, paid analysis stops. A legacy `.vision_usage.json` next to the database is imported automatically before the first paid request.
- **Limits cap local estimates, not actual OpenAI invoices.** The configurable per-analysis estimate may differ from actual charges by model, image and token usage. Use a conservative estimate and inspect your provider usage separately.

The default ledger is `.ai_usage.sqlite3` next to app.py and stores counters and random scan IDs only, not eBay listings or credentials. It survives app reruns and restarts **while that disk file remains available**. Streamlit Cloud disk is not guaranteed durable: redeployment, hibernation or replacement may remove it, resetting local day/month accounting. For continuous enforcement across deployments, set `AI_USAGE_DB` to an existing directory on durable storage shared by the app instance(s). Multiple machines need a compatible shared storage/database design; this ZIP does not add an external accounting service. Do not delete an existing ledger when updating locally.

## Secrets and local launch

Cloud: retain your existing `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`, `EBAY_MARKETPLACE_ID`, `OPENAI_API_KEY` and optional `OPENAI_VISION_MODEL`. Cloud Secrets take precedence over local `.env`. The original photo model default is retained; keep your currently working model setting if configured.

Windows, from the extracted folder:

```text
py -m pip install -r requirements.txt
copy .env.example .env
py -m streamlit run app.py
```

Enter credentials only in the local `.env` or Streamlit Secrets. Optional `METALS_DEV_API_KEY` retains the original live spot provider. Without it, spot is a manual assumption, labeled as such; the default $50 is not a live quote.

Without eBay credentials, **Demo mode** remains available. Demo listings have no real photo or eBay URLs, so the top-deals button is disabled and titles are plain text. Photo Lab works if an OpenAI key is configured.

## Tests

```text
py test_v22.py
```

21 automated tests passed on Python 3.12 / Streamlit 1.63.0. Tests exercise valuation math; plate text overriding vision; conflicting weights; numeric weights not mistaken for purity; visual construction warnings; unknown shipping; escaped eBay links; zero and exact budget boundaries; per-scan, daily and monthly caps; simultaneous reservations; corrupt ledgers; legacy usage import; failure accounting; automatic/manual sharing; duplicate-click prevention; eBay/OpenAI request contracts; and Streamlit demo/calculator/manual-OFF reruns.

eBay and OpenAI responses were simulated. The build did not use your credentials, incur paid photo calls, update GitHub or deploy your Streamlit app. Follow the small live smoke test above after uploading. Full browser layout/phone rendering was not exercised by the headless UI tests.
