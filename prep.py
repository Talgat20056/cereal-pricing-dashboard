"""
prep.py - Dominick's Finer Foods (Kilts Center) ready-to-eat cereal: data prep for the
cereal pricing / revenue-management portfolio dashboard.

Pipeline
  1. Load raw UPC + weekly store movement files (category "cer").
  2. Clean: keep OK rows, positive price/units, parse pack size, map brands, drop non-cereal /
     trial-size items, flag price outliers.
  3. Validate: row counts, nulls, duplicates, outliers, week coverage (printed + written to
     output/data_quality_report.md).
  4. Estimate own-price elasticity per brand (log-log, UPC x store and week fixed effects,
     promo control, clustered SE).
  5. Export a star schema (1 fact + dims) as CSV into /output, plus metrics.json used by docs.

Usage:  python prep.py [--raw data/raw] [--out output]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

OZ_TO_G = 28.349523125
WEEK1_START = pd.Timestamp("1989-09-14")  # Dominick's week 1 (manual, Part 8 decode table)
MIN_PACK_OZ = 5.0                           # below this = trial / single-serve, not shelf packs
ELASTICITY_PLAUSIBLE = (-5.0, -0.3)         # task rule: outside this range -> investigate / flag

# --------------------------------------------------------------------------------------
# Brand (manufacturer) mapping: UPC company prefix first, description keyword overrides.
# Dominick's UPC = 10 digits = 5-digit company prefix + 5-digit item (check digit dropped).
# --------------------------------------------------------------------------------------
PREFIX_BRAND = {
    "16000": "General Mills",
    "38000": "Kellogg's",
    "43000": "Post",
    "30000": "Quaker",
    "13130": "Nabisco",
    "17800": "Ralston",
    "38281": "Private Label",   # Dominick's / Heritage House store brands
    "41173": "Private Label",
    "42400": "Malt-O-Meal",
}
DESC_BRAND_OVERRIDES = [
    (r"^~?NAB(ISCO)?\b", "Nabisco"),           # Nabisco cereals later sold under Post's 43000 prefix
    (r"^~?DOM(INICK'?S)?\b", "Private Label"),
    (r"^HH\b", "Private Label"),               # Heritage House (Dominick's private label)
    (r"RALSTON|CHEX\b|SPIDERMAN|ALMOND DELIGHT|MUESLI|BATMAN|NINTENDO|URKEL|JETSON|HOT WHEELS|GHOST BUSTERS|BILL & TED|BARBIE|ADDAMS|PRINCE OF THIEVES|COOKIE CRISP|OAT BRAN OPTIONS|BREAKFAST ON THE RUN|RICE BRAN OP", "Ralston"),
]
# Non-cereal or non-shelf items to exclude (Pop-Tarts, shippers, apparel, hot cereal, wheat germ)
EXCLUDE_DESC = re.compile(
    r"POP TART|T-SH|SHIPPER|MAG SHI|KRETCH|WHEAT GERM|QUICK OATS|CREAM OF RIC|TRIAL|TRAIL SIZE|"
    r"VARIETY PAC|FUN PAK|BREAKFAST PACK|SINGLE VARIETY|JUMBO ASSORT|T-SIZE|SPEC-K-HAN|ASSORT",
    re.I,
)

# Product line (sub-brand) patterns, checked in order. Fallback = cleaned description.
PRODUCT_LINE_PATTERNS = [
    (r"CHEERIOS|CHERRIOS|CHEER\b|CHERR\b|TASTEEO|TASTEE", "Cheerios / Toasted Oat Rings"),
    (r"FROSTED FL|FRSTED FLKS|FROSTED FLAK|SUGAR FROST", "Frosted Flakes"),
    (r"CORN FLAKE|CORN FLA\b", "Corn Flakes"),
    (r"RAISIN BRAN|RAISIN BRA\b|RSN BRAN|X-RAISIN", "Raisin Bran"),
    (r"RICE KRISP|RICE CRISP|CRISPY RICE|COCOA KRISP|FRSTD RIC", "Rice Krispies"),
    (r"SPECIAL K", "Special K"),
    (r"FROOT LOOPS|FRUIT LOOPS|FRUIT RINGS", "Froot Loops"),
    (r"CORN POPS", "Corn Pops"),
    (r"MINI WH|MINI WHEATS|FRSTD MINI|FROSTED MINI|CINN MINI", "Frosted Mini-Wheats"),
    (r"APPLE JACK", "Apple Jacks"),
    (r"CRISPIX", "Crispix"),
    (r"PRODUCT 19", "Product 19"),
    (r"ALL BRAN|BRAN FLAKES|COMPLETE BRAN|40\+", "Bran Flakes / All-Bran"),
    (r"NUTRI.?GRAIN|NUTRI GRAN", "Nutri-Grain"),
    (r"JUST R|JST RT", "Just Right"),
    (r"MUESLIX|MUSELIX", "Mueslix"),
    (r"HONEY SMACK|SMACKS", "Honey Smacks"),
    (r"CRACKLIN", "Cracklin' Oat Bran"),
    (r"POP TART", "Pop-Tarts"),
    (r"TOTAL", "Total"),
    (r"WHEATIES", "Wheaties"),
    (r"LUCKY CHARMS", "Lucky Charms"),
    (r"TRIX", "Trix"),
    (r"KIX", "Kix"),
    (r"GOLDEN GRAHAMS", "Golden Grahams"),
    (r"CINNAMON TOAST", "Cinnamon Toast Crunch"),
    (r"COCOA PUFFS", "Cocoa Puffs"),
    (r"COUNT CHOCULA|FRANKENBERRY", "Monster Cereals"),
    (r"OATMEAL CRISP|OATMEAL RAISIN|OATML RSN|OATMEAL RSN", "Oatmeal Crisp"),
    (r"RAISIN NUT BRAN", "Raisin Nut Bran"),
    (r"BASIC 4|BASIC\b", "Basic 4"),
    (r"CLUSTE|CLUSTERS", "Clusters"),
    (r"FIBER ONE", "Fiber One"),
    (r"TRIPLES", "Triples"),
    (r"GRAPE.?NUT", "Grape-Nuts"),
    (r"HONEY ?COMB", "Honeycomb"),
    (r"PEBBLES", "Pebbles"),
    (r"ALPHA.?BITS|ALPH\b", "Alpha-Bits"),
    (r"HONEY BUNCHES", "Honey Bunches of Oats"),
    (r"GREAT GRAINS|GRT GR", "Great Grains"),
    (r"FRUIT ?& ?FIB|FRT&FIB", "Fruit & Fibre"),
    (r"SHRED|SHREDDED|SPOON SIZE|FROSTED WHE|FROST WHEAT|FRST BRAN", "Shredded Wheat"),
    (r"SUGAR CRISP|GOLDEN CRISP", "Golden Crisp"),
    (r"TOASTIES", "Post Toasties"),
    (r"BRAN'?NOLA|BRN'NOLA", "Bran'nola"),
    (r"CAP'?N|CAPN|CAPTAIN", "Cap'n Crunch"),
    (r"LIFE CEREAL|LIFE CINN", "Life"),
    (r"OAT SQU", "Oatmeal Squares"),
    (r"100% NATURAL|100% CEREAL|NATURAL LOWFA", "Quaker 100% Natural"),
    (r"OH'S", "Oh!s"),
    (r"PUFFED", "Puffed Rice / Wheat"),
    (r"CHEX", "Chex"),
    (r"MUESLI", "Muesli"),
    (r"ALMOND DELIGHT", "Almond Delight"),
    (r"COOKIE CRISP", "Cookie Crisp"),
    (r"MALT O MEAL", "Malt-O-Meal"),
    (r"100% BRAN", "100% Bran"),
    (r"TEAM FLAKES", "Team Flakes"),
    (r"FRUIT WHEATS|FRUIT\b.*WHEAT", "Fruit Wheats"),
    (r"TEDDY GRAHAM", "Teddy Grahams"),
]


def parse_pack_oz(size: str, descrip: str) -> float:
    """Return pack size in ounces, or NaN if it cannot be parsed from SIZE (never guessed)."""
    s = str(size).strip().upper()
    if s in ("", "NAN", "END", "ASST", "ASSTD") or s.endswith(" CT") or s.endswith(" EA"):
        return np.nan
    m = re.match(r"^(\d+)\s*/\s*(\d+(?:\.\d+)?)\s*(OZ|O|Z)?$", s)   # "2/20 O" = club pack 2 x 20 oz
    if m:
        return float(m.group(1)) * float(m.group(2))
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(OZ|O|Z)?$", s)
    if m:
        return float(m.group(1))
    return np.nan


def map_brand(upc: int, descrip: str) -> str:
    d = str(descrip).upper().strip()
    for pat, brand in DESC_BRAND_OVERRIDES:
        if re.search(pat, d):
            return brand
    u = str(int(upc))
    if "9166" in u[:6]:                      # 79166xxxxx / 9166xxxxxx = Ralston Purina licensed cereals
        return "Ralston"
    prefix = u.zfill(10)[:5]
    return PREFIX_BRAND.get(prefix, "Other")


def map_product_line(descrip: str) -> str:
    d = str(descrip).upper().strip().lstrip("~$").strip()
    for pat, line in PRODUCT_LINE_PATTERNS:
        if re.search(pat, d):
            return line
    return d.title()


def pack_tier(oz: float) -> str:
    if np.isnan(oz):
        return "Unknown"
    if oz < 12:
        return "1. Small (<12 oz)"
    if oz < 16:
        return "2. Medium (12-16 oz)"
    if oz < 20:
        return "3. Large (16-20 oz)"
    if oz < 30:
        return "4. Family (20-30 oz)"
    return "5. Club (30+ oz)"


def clean_desc(d: str) -> str:
    return re.sub(r"\s+", " ", str(d).strip().lstrip("~$").strip()).title()


# --------------------------------------------------------------------------------------
# Fixed-effects log-log elasticity
# --------------------------------------------------------------------------------------
def demean_two_way(df: pd.DataFrame, cols: list[str], g1: str, g2: str, iters: int = 12) -> pd.DataFrame:
    """Alternating-projection demeaning on two unbalanced fixed-effect groups."""
    x = df[cols].to_numpy(dtype=float).copy()
    a = df[g1].to_numpy()
    b = df[g2].to_numpy()
    for _ in range(iters):
        for g in (a, b):
            m = pd.DataFrame(x).groupby(g).transform("mean").to_numpy()
            x = x - m
    return pd.DataFrame(x, columns=cols, index=df.index)


def fe_elasticity(panel: pd.DataFrame, label: str, unit_col: str, time_col: str, controls: tuple = ("promo",)) -> dict:
    """
    ln(units) = e * ln(price) + b * promo + alpha_unit + gamma_week + u
    Standard errors clustered by unit (UPC x store). Returns coef, SE, 95% CI, within-R2, n.
    """
    controls = list(controls)
    d = panel[[unit_col, time_col, "ln_q", "ln_p"] + controls].dropna()
    # need within-unit price variation: drop units with < 8 obs
    cnt = d.groupby(unit_col)["ln_q"].transform("size")
    d = d[cnt >= 8]
    if len(d) < 200:
        return {"brand": label, "elasticity": np.nan, "n_obs": int(len(d)), "note": "too few observations"}
    dm = demean_two_way(d, ["ln_q", "ln_p"] + controls, unit_col, time_col)
    X = dm[["ln_p"] + controls].to_numpy()
    y = dm["ln_q"].to_numpy()
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    n, k = X.shape
    XtX_inv = np.linalg.inv(X.T @ X)
    # cluster-robust covariance (by unit)
    clusters = d[unit_col].to_numpy()
    order = np.argsort(clusters, kind="stable")
    Xs, rs, cs = X[order], resid[order], clusters[order]
    bounds = np.flatnonzero(np.r_[True, cs[1:] != cs[:-1], True])
    meat = np.zeros((k, k))
    for i in range(len(bounds) - 1):
        xe = Xs[bounds[i]:bounds[i + 1]].T @ rs[bounds[i]:bounds[i + 1]]
        meat += np.outer(xe, xe)
    G = len(bounds) - 1
    adj = (G / (G - 1)) * ((n - 1) / (n - k))
    V = adj * XtX_inv @ meat @ XtX_inv
    se = np.sqrt(np.diag(V))
    r2_within = 1 - (resid @ resid) / (y @ y)
    e, se_e = beta[0], se[0]
    return {
        "brand": label,
        "elasticity": float(e),
        "std_error": float(se_e),
        "ci_low": float(e - 1.96 * se_e),
        "ci_high": float(e + 1.96 * se_e),
        "promo_lift_coef": float(beta[1]) if controls else np.nan,
        "r2_within": float(r2_within),
        "n_obs": int(n),
        "n_units": int(G),
        "n_upcs": int(d[unit_col].str.split("|").str[0].nunique()),
        "n_stores": int(d[unit_col].str.split("|").str[1].nunique()),
        "method": "OLS log-log, UPC x store FE + week FE, promo control, SE clustered by UPC x store",
    }


def plausibility_flag(e: float) -> str:
    if np.isnan(e):
        return "NOT ESTIMATED"
    lo, hi = ELASTICITY_PLAUSIBLE
    if e > 0:
        return "IMPLAUSIBLE (positive)"
    if e > hi:
        return "FLAG: inelastic (> -0.3)"
    if e < lo:
        return "FLAG: very elastic (< -5)"
    return "OK"


# --------------------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--out", default="output")
    args = ap.parse_args()
    raw, out = Path(args.raw), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    log: list[str] = []

    def say(msg: str = "") -> None:
        print(msg)
        log.append(msg)

    say("# Data quality report - Dominick's RTE cereal (category code 'cer')")
    say(f"_Generated by prep.py on {pd.Timestamp.today():%Y-%m-%d}_\n")

    # ---------------- UPC master ----------------
    upc = pd.read_csv(raw / "upccer.csv", encoding="latin-1")
    upc.columns = [c.upper() for c in upc.columns]
    say("## 1. UPC master (upccer.csv)")
    say(f"- rows: {len(upc):,}; unique UPC: {upc['UPC'].nunique():,}; nulls per column: {upc.isna().sum().to_dict()}")
    upc["pack_oz"] = [parse_pack_oz(s, d) for s, d in zip(upc["SIZE"], upc["DESCRIP"])]
    upc["brand"] = [map_brand(u, d) for u, d in zip(upc["UPC"], upc["DESCRIP"])]
    upc["product_line"] = upc["DESCRIP"].map(map_product_line)
    upc["description"] = upc["DESCRIP"].map(clean_desc)
    upc["excluded_reason"] = ""
    upc.loc[upc["DESCRIP"].str.contains(EXCLUDE_DESC), "excluded_reason"] = "non-cereal / shipper / variety pack"
    unparsed = upc["pack_oz"].isna() & (upc["excluded_reason"] == "")
    upc.loc[unparsed, "excluded_reason"] = "pack size not parseable (SIZE='" + upc.loc[unparsed, "SIZE"].astype(str) + "')"
    small = (upc["pack_oz"] < MIN_PACK_OZ) & (upc["excluded_reason"] == "")
    upc.loc[small, "excluded_reason"] = f"trial / single-serve (< {MIN_PACK_OZ:g} oz)"
    keep_upc = upc[upc["excluded_reason"] == ""].copy()
    say(f"- UPCs kept: {len(keep_upc):,}; excluded: {(upc['excluded_reason'] != '').sum():,}")
    for reason, n in upc.loc[upc["excluded_reason"] != "", "excluded_reason"].str.replace(r"\(SIZE=.*\)", "", regex=True).value_counts().items():
        say(f"  - {n:>3} x {reason.strip()}")
    say("- pack size distribution (oz) of kept UPCs: " + ", ".join(f"p{p}={keep_upc['pack_oz'].quantile(p/100):.1f}" for p in (0, 10, 50, 90, 100)))
    say("- UPCs per brand: " + ", ".join(f"{b}={n}" for b, n in keep_upc["brand"].value_counts().items()))
    upc[["UPC", "DESCRIP", "SIZE", "pack_oz", "brand", "product_line", "excluded_reason"]].to_csv(out / "upc_mapping_audit.csv", index=False)

    # ---------------- Movement ----------------
    say("\n## 2. Weekly store movement (wcer.csv)")
    mv = pd.read_csv(
        raw / "wcer" / "wcer.csv",
        usecols=["STORE", "UPC", "WEEK", "MOVE", "QTY", "PRICE", "SALE", "PROFIT", "OK"],
        dtype={"SALE": "string"},
    )
    n_raw = len(mv)
    say(f"- raw rows: {n_raw:,}; stores: {mv['STORE'].nunique()}; UPCs: {mv['UPC'].nunique()}; weeks {mv['WEEK'].min()}-{mv['WEEK'].max()} ({mv['WEEK'].nunique()} distinct)")
    say(f"- nulls per column: { {k: int(v) for k, v in mv.isna().sum().items() if k != 'SALE'} } (SALE blank = no recorded promo: {int(mv['SALE'].isna().sum()):,})")
    dups = int(mv.duplicated(["STORE", "UPC", "WEEK"]).sum())
    say(f"- duplicate (store, upc, week) keys: {dups:,}")
    assert dups == 0, "unexpected duplicate keys"
    weeks_all = set(range(int(mv["WEEK"].min()), int(mv["WEEK"].max()) + 1))
    missing_weeks = sorted(weeks_all - set(mv["WEEK"].unique()))
    say(f"- weeks with no data at all (chain-wide gaps in source): {len(missing_weeks)} -> {missing_weeks}")

    n0 = len(mv)
    mv = mv[mv["OK"] == 1]; n_ok = n0 - len(mv)
    n1 = len(mv)
    mv = mv[(mv["MOVE"] > 0) & (mv["PRICE"] > 0) & (mv["QTY"] >= 1)]; n_zero = n1 - len(mv)
    n2 = len(mv)
    mv = mv[mv["UPC"].isin(keep_upc["UPC"])]; n_excl_upc = n2 - len(mv)
    say(f"- dropped OK=0 (flagged by Kilts as suspect): {n_ok:,}")
    say(f"- dropped zero units / zero price (no sale that week): {n_zero:,}")
    say(f"- dropped rows of excluded UPCs: {n_excl_upc:,}")

    mv = mv.merge(keep_upc[["UPC", "pack_oz", "brand"]], on="UPC", how="left")
    mv["pack_price"] = mv["PRICE"] / mv["QTY"]                 # price of one package (bundles unwound)
    mv["revenue"] = mv["PRICE"] * mv["MOVE"] / mv["QTY"]      # manual: Sales = Price * Move / Qty
    mv["volume_oz"] = mv["MOVE"] * mv["pack_oz"]
    mv["promo"] = mv["SALE"].notna().astype(np.int8)          # B=bonus buy, C=coupon, S=price cut (+ G/L undocumented)

    # price outliers: relative to each UPC's median package price (catch keying errors, not promos)
    med = mv.groupby("UPC")["pack_price"].transform("median")
    ratio = mv["pack_price"] / med
    outlier = (ratio > 2.5) | (ratio < 0.35)
    say(f"- price outliers vs UPC median (x>2.5 or x<0.35): {int(outlier.sum()):,} rows ({outlier.mean():.3%}) removed")
    q_hi = mv["MOVE"].quantile(0.9999)
    say(f"- units/week p50={mv['MOVE'].median():.0f}, p99={mv['MOVE'].quantile(0.99):.0f}, p99.99={q_hi:.0f}, max={mv['MOVE'].max():,.0f} (kept; large values are real promo weeks)")
    mv = mv[~outlier].copy()
    say(f"- **final fact rows: {len(mv):,}** ({len(mv)/n_raw:.1%} of raw)")
    say(f"- revenue total: ${mv['revenue'].sum():,.0f}; units: {mv['MOVE'].sum():,.0f}; promo-flagged rows: {mv['promo'].mean():.1%}")

    # ---------------- Dates ----------------
    weeks = pd.DataFrame({"week_id": sorted(mv["WEEK"].unique())})
    weeks["week_start"] = WEEK1_START + pd.to_timedelta((weeks["week_id"] - 1) * 7, unit="D")
    weeks["week_end"] = weeks["week_start"] + pd.Timedelta(days=6)
    weeks["year"] = weeks["week_start"].dt.year
    weeks["quarter"] = "Q" + weeks["week_start"].dt.quarter.astype(str)
    weeks["year_quarter"] = weeks["year"].astype(str) + " " + weeks["quarter"]
    weeks["month_num"] = weeks["week_start"].dt.month
    weeks["month"] = weeks["week_start"].dt.strftime("%b")
    weeks["year_month"] = weeks["week_start"].dt.strftime("%Y-%m")
    weeks["year_month_sort"] = weeks["year"] * 100 + weeks["month_num"]
    say(f"- calendar: week {weeks['week_id'].min()} ({weeks['week_start'].min():%Y-%m-%d}) to week {weeks['week_id'].max()} ({weeks['week_end'].max():%Y-%m-%d}); {len(weeks)} weeks with sales")

    # ---------------- Stores ----------------
    demo = pd.read_stata(raw / "demo" / "demo.dta")
    demo = demo[demo["store"].notna()].copy()
    demo["store"] = demo["store"].astype(int)
    demo["price_tier"] = np.select(
        [demo["prichigh"] == 1, demo["pricmed"] == 1, demo["priclow"] == 1],
        ["High", "Medium", "Low"], default="Unknown",
    )
    stores = pd.DataFrame({"store_id": sorted(mv["STORE"].unique())}).merge(
        demo[["store", "city", "zip", "zone", "price_tier", "scluster", "income", "weekvol"]].rename(columns={"store": "store_id"}),
        on="store_id", how="left",
    )
    stores["price_tier"] = stores["price_tier"].fillna("Unknown")
    stores["city"] = stores["city"].fillna("").str.strip().str.title().replace("", "Unknown")
    stores["zone"] = stores["zone"].fillna(0).astype(int)
    stores["zip"] = stores["zip"].map(lambda z: "" if pd.isna(z) else str(int(z)))
    stores["store_cluster"] = stores["scluster"].fillna("").astype(str).str.strip().replace("", "Unknown")
    stores["log_median_income"] = stores["income"].round(3)
    stores["weekly_volume_k"] = stores["weekvol"]
    stores["store_name"] = "Store " + stores["store_id"].astype(str) + " - " + stores["city"]
    stores = stores[["store_id", "store_name", "city", "zip", "zone", "price_tier", "store_cluster", "log_median_income", "weekly_volume_k"]]
    say(f"- stores in fact: {len(stores)}; price tier counts: {stores['price_tier'].value_counts().to_dict()} (Dominick's pricing zones: High / Medium / Low='Cub fighter')")

    # ---------------- Product dim ----------------
    prod = keep_upc[keep_upc["UPC"].isin(mv["UPC"])].copy()
    prod = prod.rename(columns={"UPC": "upc"})
    prod["pack_g"] = (prod["pack_oz"] * OZ_TO_G).round(0)
    prod["pack_tier"] = prod["pack_oz"].map(pack_tier)
    prod["pack_label"] = prod["pack_oz"].map(lambda x: f"{x:g} oz")
    prod["is_private_label"] = (prod["brand"] == "Private Label")
    prod["product"] = prod["description"] + " " + prod["pack_label"]
    prod = prod[["upc", "product", "description", "brand", "product_line", "pack_oz", "pack_g", "pack_tier", "pack_label", "is_private_label"]]

    # ---------------- Elasticity ----------------
    say("\n## 3. Own-price elasticity by brand")
    say("Model: ln(units) = e*ln(pack price) + b*promo + UPC x store FE + week FE; SE clustered by UPC x store.")
    say("Identification comes from within-UPC-within-store weekly price changes (temporary price cuts, Dominick's")
    say("zone pricing experiments), so e is a short-run promotional/own-price elasticity, not a long-run list-price elasticity.")
    mv["unit"] = mv["UPC"].astype(str) + "|" + mv["STORE"].astype(str)
    mv["ln_q"] = np.log(mv["MOVE"])
    mv["ln_p"] = np.log(mv["pack_price"])
    results = []
    brands = [b for b in mv.groupby("brand")["revenue"].sum().sort_values(ascending=False).index]
    for b in brands:
        sub = mv[mv["brand"] == b]
        r = fe_elasticity(sub, b, "unit", "WEEK")
        r["flag"] = plausibility_flag(r.get("elasticity", np.nan))
        r["revenue_share"] = float(sub["revenue"].sum() / mv["revenue"].sum())
        results.append(r)
        say(f"- {b:<14} e={r.get('elasticity', np.nan):+.3f}  95% CI [{r.get('ci_low', np.nan):+.3f}, {r.get('ci_high', np.nan):+.3f}]  "
            f"within-R2={r.get('r2_within', np.nan):.3f}  n={r.get('n_obs', 0):,}  UPCs={r.get('n_upcs', 0)}  stores={r.get('n_stores', 0)}  {r['flag']}")
    cat = fe_elasticity(mv, "Category (all brands)", "unit", "WEEK")
    cat["flag"] = plausibility_flag(cat["elasticity"]); cat["revenue_share"] = 1.0
    say(f"- {'CATEGORY':<14} e={cat['elasticity']:+.3f}  95% CI [{cat['ci_low']:+.3f}, {cat['ci_high']:+.3f}]  within-R2={cat['r2_within']:.3f}  n={cat['n_obs']:,}")
    # robustness: no promo control (pure price variation incl. promo weeks)
    say("- robustness (same FE, promo control dropped):")
    rob = {}
    for b in brands[:5]:
        rr = fe_elasticity(mv[mv["brand"] == b], b, "unit", "WEEK", controls=())
        rob[b] = rr["elasticity"]
        say(f"    {b:<14} e={rr['elasticity']:+.3f}")
    elas = pd.DataFrame(results + [cat])
    elas = elas[["brand", "elasticity", "std_error", "ci_low", "ci_high", "promo_lift_coef", "r2_within", "n_obs", "n_units", "n_upcs", "n_stores", "revenue_share", "flag", "method"]]
    elas["elasticity_no_promo_control"] = elas["brand"].map(rob)

    # ---------------- Fact ----------------
    fact = mv[["STORE", "UPC", "WEEK", "MOVE", "revenue", "volume_oz", "pack_price", "promo"]].rename(
        columns={"STORE": "store_id", "UPC": "upc", "WEEK": "week_id", "MOVE": "units"}
    )
    fact["revenue"] = fact["revenue"].round(2)
    fact["volume_oz"] = fact["volume_oz"].round(1)
    fact["pack_price"] = fact["pack_price"].round(4)
    fact = fact.sort_values(["week_id", "store_id", "upc"])

    # referential integrity checks
    assert fact["upc"].isin(prod["upc"]).all()
    assert fact["store_id"].isin(stores["store_id"]).all()
    assert fact["week_id"].isin(weeks["week_id"]).all()
    assert prod["upc"].is_unique and stores["store_id"].is_unique and weeks["week_id"].is_unique
    say("\n## 4. Star schema export")
    fact.to_csv(out / "fact_sales.csv", index=False)
    prod.to_csv(out / "dim_product.csv", index=False)
    stores.to_csv(out / "dim_store.csv", index=False)
    weeks.to_csv(out / "dim_week.csv", index=False, date_format="%Y-%m-%d")
    elas.to_csv(out / "dim_brand_elasticity.csv", index=False)
    for f in ("fact_sales", "dim_product", "dim_store", "dim_week", "dim_brand_elasticity"):
        p = out / f"{f}.csv"
        say(f"- {p.name}: {sum(1 for _ in open(p, encoding='utf-8')) - 1:,} rows, {p.stat().st_size/1e6:.1f} MB")
    say("- referential integrity fact -> dims: OK (all keys resolve, dim keys unique)")

    # ---------------- Metrics for docs (every number in docs comes from here) ----------------
    say("\n## 5. Headline metrics (also written to metrics.json)")
    f2 = fact.merge(prod[["upc", "brand", "pack_tier", "pack_oz", "product_line"]], on="upc").merge(stores[["store_id", "price_tier"]], on="store_id").merge(weeks[["week_id", "year"]], on="week_id")
    f2["g"] = f2["volume_oz"] * OZ_TO_G
    def p100g(d: pd.DataFrame) -> float:
        return float(d["revenue"].sum() / d["g"].sum() * 100)
    cat_p100 = p100g(f2)
    brand_p100 = f2.groupby("brand").apply(p100g, include_groups=False).sort_values(ascending=False)
    brand_index = (brand_p100 / cat_p100 * 100).round(1)
    tier_p100 = f2.groupby("pack_tier").apply(p100g, include_groups=False)
    brand_tier = f2.groupby(["brand", "pack_tier"]).apply(p100g, include_groups=False).unstack()
    store_tier_idx = (f2.groupby("price_tier").apply(p100g, include_groups=False) / cat_p100 * 100).round(1)
    rev_share = (f2.groupby("brand")["revenue"].sum() / f2["revenue"].sum()).sort_values(ascending=False)
    # pack-size discount: compare the largest vs smallest tier for the biggest brands
    big = brand_tier.loc[rev_share.index[:4]]
    # price index over time for private label vs category (yearly)
    pl_year = f2[f2["brand"] == "Private Label"].groupby("year").apply(p100g, include_groups=False)
    cat_year = f2.groupby("year").apply(p100g, include_groups=False)
    pl_idx_year = (pl_year / cat_year * 100).round(1)
    # yearly price index by brand (for monitoring narrative)
    brand_year_idx = (f2.groupby(["brand", "year"]).apply(p100g, include_groups=False).unstack() / cat_year * 100).round(1)
    # what-if: +5% on top brand with its elasticity
    top_brand = rev_share.index[0]
    e_top = float(elas.loc[elas["brand"] == top_brand, "elasticity"].iloc[0])
    rev_top = float(f2.loc[f2["brand"] == top_brand, "revenue"].sum())
    whatif = {}
    for pct in (0.05, 0.10):
        vol_chg = (1 + pct) ** e_top - 1
        rev_chg = (1 + pct) ** (1 + e_top) - 1
        whatif[f"+{pct:.0%}"] = {"volume_change": round(vol_chg, 4), "revenue_change": round(rev_chg, 4), "revenue_delta_usd": round(rev_top * rev_chg, 0)}
    # breakeven: price increase x where revenue change = 0 happens only if e = -1; report revenue-max
    metrics = {
        "data": {
            "source": "Dominick's Finer Foods scanner data, Kilts Center for Marketing, University of Chicago Booth School of Business",
            "category": "Ready-to-eat cereal (cer)",
            "raw_rows": int(n_raw), "fact_rows": int(len(fact)), "upcs": int(len(prod)), "stores": int(len(stores)),
            "weeks": int(len(weeks)), "first_week": f"{weeks['week_start'].min():%Y-%m-%d}", "last_week": f"{weeks['week_end'].max():%Y-%m-%d}",
            "brands": brands, "total_revenue_usd": round(float(fact["revenue"].sum()), 0), "total_units": int(fact["units"].sum()),
            "promo_row_share": round(float(fact["promo"].mean()), 4), "price_outlier_rows_removed": int(outlier.sum()),
            "ok0_rows_removed": int(n_ok), "zero_sale_rows_removed": int(n_zero), "excluded_upc_rows_removed": int(n_excl_upc),
            "missing_weeks": missing_weeks,
        },
        "category_price_per_100g_usd": round(cat_p100, 4),
        "brand_price_per_100g_usd": {k: round(v, 4) for k, v in brand_p100.items()},
        "brand_price_index_vs_category": brand_index.to_dict(),
        "brand_revenue_share": {k: round(float(v), 4) for k, v in rev_share.items()},
        "pack_tier_price_per_100g_usd": {k: round(v, 4) for k, v in tier_p100.items()},
        "brand_x_pack_tier_price_per_100g_usd": {b: {t: (None if pd.isna(v) else round(v, 4)) for t, v in row.items()} for b, row in brand_tier.iterrows()},
        "store_price_tier_index_vs_category": store_tier_idx.to_dict(),
        "private_label_index_by_year": {int(k): v for k, v in pl_idx_year.items()},
        "brand_index_by_year": {b: {int(y): (None if pd.isna(v) else v) for y, v in row.items()} for b, row in brand_year_idx.iterrows()},
        "elasticity": elas.drop(columns=["method"]).to_dict(orient="records"),
        "what_if_top_brand": {"brand": top_brand, "elasticity": round(e_top, 3), "baseline_revenue_usd": round(rev_top, 0), "scenarios": whatif},
    }
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2, default=float), encoding="utf-8")
    say(f"- category price per 100 g: ${cat_p100:.4f}")
    say("- brand price index vs category (100 = category): " + ", ".join(f"{b}={v}" for b, v in brand_index.items()))
    say("- brand revenue share: " + ", ".join(f"{b}={v:.1%}" for b, v in rev_share.items()))
    say("- pack-tier price per 100 g: " + ", ".join(f"{t}=${v:.3f}" for t, v in tier_p100.items()))
    say("- store price-tier index vs category: " + ", ".join(f"{t}={v}" for t, v in store_tier_idx.items()))
    say(f"- what-if, {top_brand} (e={e_top:+.2f}): " + "; ".join(f"{k}: volume {v['volume_change']:+.1%}, revenue {v['revenue_change']:+.1%} (${v['revenue_delta_usd']:+,.0f})" for k, v in whatif.items()))
    say(f"\n_Runtime: {time.time() - t0:.0f} s_")
    (out / "data_quality_report.md").write_text("\n".join(log), encoding="utf-8")


if __name__ == "__main__":
    main()
