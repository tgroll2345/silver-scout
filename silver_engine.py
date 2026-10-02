from __future__ import annotations
from dataclasses import dataclass, asdict
import re
import math
from typing import Optional

TROY_OZ_TO_GRAMS = 31.1034768


PLATE_PATTERN = re.compile(r"\b(?:silver[\s-]*plat(?:e[ds]?|ing)|e\.?p\.?n\.?s\.?|nickel silver|german silver|quadruple plate)\b", re.I)


def explicit_plate(text: str) -> bool:
    return bool(PLATE_PATTERN.search(text))


def term_found(term: str, text: str) -> bool:
    suffix = r"(?!\w)"
    if term.isdigit():
        suffix += r"(?!\s*(?:grams?|g|oz|ounces?|ozt|troy|lbs?|pounds?)\b)"
    return bool(re.search(r"(?<![\w.])" + re.escape(term) + suffix, text))

PURITY_MAP = {
    "999": 0.999,
    "958": 0.958,
    "925": 0.925,
    "sterling": 0.925,
    "coin silver": 0.900,
    "900": 0.900,
    "835": 0.835,
    "830": 0.830,
    "800": 0.800,
}

NEGATIVE_TERMS = {
    "silverplate": 70,
    "silver plated": 70,
    "silver-plated": 70,
    "epns": 75,
    "a1": 45,
    "quadruple plate": 80,
    "stainless": 40,
    "nickel silver": 80,
    "german silver": 80,
}

RISK_TERMS = {
    "weighted": 35,
    "cement filled": 45,
    "filled": 20,
    "hollow handle": 25,
    "hollow-handled": 25,
    "knife": 12,
    "knives": 12,
}

POSITIVE_TERMS = {
    "sterling": 45,
    "925": 40,
    "900": 28,
    "835": 25,
    "830": 25,
    "800": 22,
    "coin silver": 35,
    "gorham": 8,
    "towle": 8,
    "wallace": 8,
    "reed & barton": 8,
    "tiffany": 10,
    "georg jensen": 10,
}

@dataclass
class Estimate:
    title: str
    total_cost: float
    estimated_gross_grams: Optional[float]
    purity: Optional[float]
    recoverable_fraction: float
    melt_value: Optional[float]
    conservative_value: Optional[float]
    est_profit: Optional[float]
    margin_pct: Optional[float]
    confidence: int
    score: int
    reasons: list[str]
    risks: list[str]
    silver_spot_used: float
    tax_rate_used: float
    realization_used: float
    weight_source: str
    discount_pct: Optional[float]

    def dict(self):
        return asdict(self)


def detect_purity(text: str) -> tuple[Optional[float], list[str]]:
    t = text.lower()
    hits = []
    # Negative metal descriptions override apparent numeric markings in text.
    if explicit_plate(t):
        return None, hits
    for term, purity in PURITY_MAP.items():
        if term_found(term, t):
            hits.append(term)
    if not hits:
        return None, []
    # Use the lowest mentioned fineness for mixed or conflicting purity evidence.
    best = min((PURITY_MAP[h], h) for h in hits)
    return best[0], hits


def extract_weight_grams(text: str) -> tuple[Optional[float], str | None]:
    t = text.lower().replace(",", "")
    patterns = [
        (r"(\d+(?:\.\d+)?)\s*(?:grams?|g)\b", 1.0, "g"),
        (r"(\d+(?:\.\d+)?)\s*(?:troy\s*oz|ozt)\b", TROY_OZ_TO_GRAMS, "ozt"),
        (r"(\d+(?:\.\d+)?)\s*(?:ounces?|oz)\b", 28.349523125, "oz"),
        (r"(\d+(?:\.\d+)?)\s*(?:lbs?|pounds?)\b", 453.59237, "lb"),
    ]
    candidates = []
    for pat, mult, unit in patterns:
        for m in re.finditer(pat, t):
            val = float(m.group(1)) * mult
            if 2 <= val <= 50000:
                context = t[max(0, m.start()-35):m.end()+25]
                if not re.search(r"shipping weight|packaged weight|package weight|with (?:the )?(?:box|case)", context):
                    candidates.append((val, unit, m.group(0)))
    if not candidates:
        return None, None
    # Multiple incompatible weights need human review, never choose the largest.
    weights = [c[0] for c in candidates]
    if max(weights) > min(weights) * 1.05:
        return None, "Conflicting weights; verify net metal weight"
    val, unit, raw = min(candidates, key=lambda x: x[0])
    return val, raw


def estimate_listing(
    title: str,
    description: str,
    price: float,
    shipping: float,
    silver_spot_per_troy_oz: float,
    tax_rate: float = 0.0,
    refining_discount: float = 0.92,
    image_evidence: dict | None = None,
) -> Estimate:
    text = f"{title} {description}".strip()
    low = text.lower()
    total_cost = (price + shipping) * (1 + tax_rate)

    purity, purity_hits = detect_purity(text)
    grams, raw_weight = extract_weight_grams(text)

    reasons, risks = [], []
    if len({PURITY_MAP[h] for h in purity_hits}) > 1:
        risks.append("Multiple purity terms: lowest fineness used; verify each piece before buying")

    # Optional photo evidence is deliberately conservative. Explicit plate terms in seller text override image guesses.
    if image_evidence:
        visual_conf = int(image_evidence.get("visual_confidence") or 0)
        plated_likelihood = int(image_evidence.get("plated_likelihood") or 0)
        silver_likelihood = int(image_evidence.get("silver_likelihood") or 0)
        image_purity = image_evidence.get("likely_purity")
        seller_plate = explicit_plate(low)
        if purity is None and image_purity and visual_conf >= 70 and silver_likelihood >= 75 and plated_likelihood <= 20 and not seller_plate:
            purity = float(image_purity) if float(image_purity) in PURITY_MAP.values() else None
            if purity is not None:
                reasons.append(f"Photo suggests solid silver purity near {purity:.3f}")
        if grams is None and raw_weight is None:
            low_g = image_evidence.get("estimated_weight_low_g")
            high_g = image_evidence.get("estimated_weight_high_g")
            if low_g and math.isfinite(float(low_g)) and 2 <= float(low_g) <= 50000 and visual_conf >= 70:
                # Always use the low end for melt valuation.
                grams = float(low_g)
                raw_weight = f"photo-estimated conservative low end {float(low_g):.0f} g"
                risks.append(f"Weight estimated from photo range {float(low_g):.0f}-{float(high_g or low_g):.0f} g, not seller-verified")
        if plated_likelihood >= 70:
            risks.append("Photo strongly suggests plated rather than solid silver")
        hallmarks = image_evidence.get("hallmark_text") or []
        if hallmarks:
            reasons.append("Photo markings: " + ", ".join(map(str, hallmarks[:4])))
    confidence = 15

    for term, pts in POSITIVE_TERMS.items():
        if term_found(term, low):
            confidence += min(pts, 25)
            if term in {"sterling", "925", "900", "835", "830", "800", "coin silver"}:
                reasons.append(f"Metal mark/term detected: {term}")

    negative_penalty = 70 if explicit_plate(low) else 0
    if explicit_plate(low):
        risks.append("Explicit silverplate/EPNS/base-metal text overrides visual sterling evidence")
    for term, pts in NEGATIVE_TERMS.items():
        if term_found(term, low):
            negative_penalty += pts
            risks.append(f"Likely non-solid silver indicator: {term}")

    risk_penalty = 0
    recoverable_fraction = 1.0
    for term, pts in RISK_TERMS.items():
        if term_found(term, low):
            risk_penalty += pts
            risks.append(f"Weight/content risk: {term}")
            if term in {"weighted", "cement filled", "filled"}:
                recoverable_fraction = min(recoverable_fraction, 0.25)
            elif term in {"hollow handle", "hollow-handled"}:
                recoverable_fraction = min(recoverable_fraction, 0.35)
            elif term in {"knife", "knives"}:
                recoverable_fraction = min(recoverable_fraction, 0.50)

    if grams is not None:
        confidence += 25
        reasons.append(f"Weight detected: {raw_weight}")
    else:
        risks.append(raw_weight or "No reliable weight found in listing text")

    if purity is not None:
        confidence += 20
    else:
        risks.append("Purity not verified from listing text")

    if image_evidence:
        visual_conf = int(image_evidence.get("visual_confidence") or 0)
        silver_likelihood = int(image_evidence.get("silver_likelihood") or 0)
        plated_likelihood = int(image_evidence.get("plated_likelihood") or 0)
        weighted_likelihood = int(image_evidence.get("weighted_likelihood") or 0)
        hollow_likelihood = int(image_evidence.get("hollow_handle_likelihood") or 0)
        knife_likelihood = int(image_evidence.get("knife_or_steel_blade_likelihood") or 0)
        if visual_conf >= 60 and silver_likelihood >= 70: confidence += 12
        if plated_likelihood >= 60: negative_penalty += 45
        if weighted_likelihood >= 60:
            recoverable_fraction = min(recoverable_fraction, 0.25)
            risk_penalty += 25
            risks.append("Photo suggests weighted construction; recovery limited to 25%")
        if hollow_likelihood >= 60:
            recoverable_fraction = min(recoverable_fraction, 0.35)
            risk_penalty += 20
            risks.append("Photo suggests hollow handles; recovery limited to 35%")
        if knife_likelihood >= 60:
            recoverable_fraction = min(recoverable_fraction, 0.35)
            risk_penalty += 15
            risks.append("Photo suggests knives/steel blades; recovery limited to 35%")

    confidence = max(0, min(100, confidence - negative_penalty - risk_penalty // 2))

    melt = conservative = profit = margin = None
    # Gross weights for sterling-handled knives with stainless blades are especially unreliable.
    if ("stainless" in low) and ("knife" in low or "knives" in low):
        recoverable_fraction = min(recoverable_fraction, 0.25)
        risks.append("Gross knife weight includes substantial non-silver blade material")

    if grams is not None and purity is not None and negative_penalty < 60:
        silver_troy_oz = (grams / TROY_OZ_TO_GRAMS) * purity * recoverable_fraction
        melt = silver_troy_oz * silver_spot_per_troy_oz
        conservative = melt * refining_discount
        profit = conservative - total_cost
        margin = (profit / total_cost * 100) if total_cost else None
        reasons.append(f"Recoverable fraction assumption: {recoverable_fraction:.0%}")
        reasons.append(f"Refining/realization factor: {refining_discount:.0%}")

    score = confidence
    if profit is not None and margin is not None:
        if profit >= 200: score += 15
        elif profit >= 75: score += 10
        elif profit > 0: score += 4
        if margin >= 75: score += 15
        elif margin >= 35: score += 10
        elif margin > 0: score += 4
    score = max(0, min(100, score))

    return Estimate(
        title=title,
        total_cost=round(total_cost, 2),
        estimated_gross_grams=None if grams is None else round(grams, 2),
        purity=purity,
        recoverable_fraction=recoverable_fraction,
        melt_value=None if melt is None else round(melt, 2),
        conservative_value=None if conservative is None else round(conservative, 2),
        est_profit=None if profit is None else round(profit, 2),
        margin_pct=None if margin is None else round(margin, 1),
        confidence=confidence,
        score=score,
        reasons=reasons,
        risks=risks,
        silver_spot_used=silver_spot_per_troy_oz,
        tax_rate_used=tax_rate,
        realization_used=refining_discount,
        weight_source=raw_weight or "Unknown",
        discount_pct=round((1 - total_cost / conservative) * 100, 1) if conservative and conservative > 0 else None,
    )
