"""
build_pbip.py - generates the Power BI Project (PBIP) from code:
  * semantic model in TMDL (tables load /output CSVs through one Power Query parameter `DataFolder`)
  * report in PBIR (one page, three modules, slicers)

Usage:  python build_pbip.py [--data-folder <abs path to output csvs>] [--out pbip]
Re-run after prep.py whenever the CSV layout changes. All ids are deterministic (uuid5), so
re-building does not churn lineage tags.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = "Cereal Pricing"
MODEL_DIR = f"{PROJECT}.SemanticModel"
REPORT_DIR = f"{PROJECT}.Report"
NS = uuid.UUID("7c9e6679-7425-40de-944b-e07fc1f90ae7")

# ---- PBIR schema set (one matched set; see DECISIONS.md) ----
SCH = "https://developer.microsoft.com/json-schemas/fabric"
S_PBIP = f"{SCH}/pbip/pbipProperties/1.0.0/schema.json"
S_PLATFORM = f"{SCH}/gitIntegration/platformProperties/2.0.0/schema.json"
S_PBISM = f"{SCH}/item/semanticModel/definitionProperties/1.0.0/schema.json"
S_EDITOR = f"{SCH}/item/semanticModel/editorSettings/1.0.0/schema.json"
S_PBIR = f"{SCH}/item/report/definitionProperties/2.0.0/schema.json"
S_REPORT = f"{SCH}/item/report/definition/report/3.3.0/schema.json"
S_VERSION = f"{SCH}/item/report/definition/versionMetadata/1.0.0/schema.json"
S_PAGES = f"{SCH}/item/report/definition/pagesMetadata/1.1.0/schema.json"
S_PAGE = f"{SCH}/item/report/definition/page/2.1.0/schema.json"
S_VISUAL = f"{SCH}/item/report/definition/visualContainer/2.9.0/schema.json"
BASE_THEME = "CY24SU10"

PAGE_W, PAGE_H = 1600, 740   # wide 2.3:1 canvas so the whole page fits a laptop screen in "fit to width"


def guid(*parts: str) -> str:
    return str(uuid.uuid5(NS, "|".join(parts)))


def hid(*parts: str) -> str:
    """20-hex-char id in the style Power BI Desktop uses for pages/visuals."""
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:20]


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Power BI Desktop writes CRLF, UTF-8 without BOM
    path.write_text(text.replace("\r\n", "\n").replace("\n", "\r\n"), encoding="utf-8", newline="")


def write_json(path: Path, obj) -> None:
    write(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


# =====================================================================================
# TMDL
# =====================================================================================
def q(name: str) -> str:
    """Quote a TMDL object name when needed."""
    if any(ch in name for ch in " .=:'()%$/-+&#") or name[0].isdigit():
        return "'" + name.replace("'", "''") + "'"
    return name


def col(name, source, dtype, *, fmt=None, summarize="none", hidden=False, sort_by=None, desc=None, key=False,
        extra_annotations=None, extended=None):
    return dict(name=name, source=source, dtype=dtype, fmt=fmt, summarize=summarize, hidden=hidden,
                sort_by=sort_by, desc=desc, key=key, extra_annotations=extra_annotations or [], extended=extended)


def measure(name, dax, *, fmt=None, desc=None, folder=None, hidden=False):
    return dict(name=name, dax=dax, fmt=fmt, desc=desc, folder=folder, hidden=hidden)


def tmdl_description(desc: str | None, indent: str) -> str:
    if not desc:
        return ""
    return "".join(f"{indent}/// {line}\n" for line in desc.strip().splitlines())


def tmdl_column(table: str, c: dict) -> str:
    i, j = "\t", "\t\t"
    out = tmdl_description(c["desc"], i)
    out += f"{i}column {q(c['name'])}\n"
    out += f"{j}dataType: {c['dtype']}\n"
    if c["hidden"]:
        out += f"{j}isHidden\n"
    if c["key"]:
        out += f"{j}isKey\n"
    if c["fmt"]:
        out += f"{j}formatString: {c['fmt']}\n"
    out += f"{j}lineageTag: {guid(table, 'col', c['name'])}\n"
    out += f"{j}summarizeBy: {c['summarize']}\n"
    out += f"{j}sourceColumn: {c['source']}\n"
    if c["sort_by"]:
        out += f"{j}sortByColumn: {q(c['sort_by'])}\n"
    out += "\n"
    if c["sort_by"]:
        out += f"{j}changedProperty = SortByColumn\n\n"
    if c["extended"]:
        name, value = c["extended"]
        out += f"{j}extendedProperty {name} =\n"
        for line in json.dumps(value, indent=2).splitlines():
            out += f"{j}\t\t{line}\n"
        out += "\n"
    out += f"{j}annotation SummarizationSetBy = User\n\n"
    for a in c["extra_annotations"]:
        out += f"{j}annotation {a}\n\n"
    return out


def tmdl_measure(table: str, m: dict) -> str:
    i, j = "\t", "\t\t"
    out = tmdl_description(m["desc"], i)
    dax = m["dax"].strip("\n")
    lines = dax.splitlines()
    if len(lines) == 1:
        out += f"{i}measure {q(m['name'])} = {lines[0].strip()}\n"
    else:
        out += f"{i}measure {q(m['name'])} =\n"
        for line in lines:
            out += f"{j}\t{line}\n" if line.strip() else "\n"
    if m["fmt"]:
        out += f"{j}formatString: {m['fmt']}\n"
    if m["hidden"]:
        out += f"{j}isHidden\n"
    if m["folder"]:
        out += f"{j}displayFolder: {m['folder']}\n"
    out += f"{j}lineageTag: {guid(table, 'measure', m['name'])}\n\n"
    return out


def m_csv_partition(file_name: str, types: list[tuple[str, str]], ncols: int) -> str:
    """M query: read <DataFolder>\\<file> with promoted headers and explicit types (en-US culture)."""
    type_list = ", ".join(f'{{"{c}", {t}}}' for c, t in types)
    return (
        "let\n"
        f'    Source = Csv.Document(File.Contents(DataFolder & "\\{file_name}"), [Delimiter = ",", Columns = {ncols}, Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),\n'
        "    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),\n"
        f'    Typed = Table.TransformColumnTypes(Headers, {{{type_list}}}, "en-US")\n'
        "in\n"
        "    Typed"
    )


def tmdl_table(name: str, desc: str, columns: list[dict], measures: list[dict], partition_kind: str,
               partition_src: str, hidden: bool = False) -> str:
    out = tmdl_description(desc, "")
    out += f"table {q(name)}\n"
    if hidden:
        out += "\tisHidden\n"
    out += f"\tlineageTag: {guid('table', name)}\n\n"
    for m in measures:
        out += tmdl_measure(name, m)
    for c in columns:
        out += tmdl_column(name, c)
    out += f"\tpartition {q(name)} = {partition_kind}\n"
    out += "\t\tmode: import\n"
    out += "\t\tsource =\n"
    for line in partition_src.splitlines():
        out += f"\t\t\t\t{line}\n" if line.strip() else "\n"
    out += "\n"
    if partition_kind == "m":
        out += "\tannotation PBI_ResultType = Table\n\n"
    return out


def build_model(out: Path, data_folder: str) -> None:
    md = out / MODEL_DIR
    md.mkdir(parents=True, exist_ok=True)
    write_json(md / ".platform", {
        "$schema": S_PLATFORM,
        "metadata": {"type": "SemanticModel", "displayName": PROJECT},
        "config": {"version": "2.0", "logicalId": guid("platform", "model")},
    })
    write_json(md / "definition.pbism", {"$schema": S_PBISM, "version": "4.2", "settings": {}})
    write_json(md / ".pbi" / "editorSettings.json", {"$schema": S_EDITOR, "autodetectRelationships": False})

    d = md / "definition"
    write(d / "database.tmdl", "database\n\tcompatibilityLevel: 1567\n\n")

    tables = ["Sales", "Product", "Store", "Calendar", "Brand", "Price Change %", "Pricing Measures"]
    model = (
        "model Model\n"
        "\tculture: en-US\n"
        "\tdefaultPowerBIDataSourceVersion: powerBI_V3\n"
        "\tsourceQueryCulture: en-US\n"
        "\tdataAccessOptions\n"
        "\t\tlegacyRedirects\n"
        "\t\treturnErrorValuesAsNull\n\n"
        "annotation __PBI_TimeIntelligenceEnabled = 0\n\n"
        f"annotation PBI_QueryOrder = {json.dumps(['DataFolder', 'Sales', 'Product', 'Store', 'Calendar', 'Brand'])}\n\n"
        'annotation PBI_ProTooling = ["DevMode"]\n\n'
        + "".join(f"ref table {q(t)}\n" for t in tables) + "\n"
    )
    write(d / "model.tmdl", model)

    # ---- single Power Query parameter for the data folder ----
    df = data_folder.rstrip("\\/").replace('"', '""')
    write(d / "expressions.tmdl",
          "/// Folder that holds the CSV files exported by prep.py (fact_sales.csv, dim_*.csv). Change this one value to repoint the model.\n"
          f'expression DataFolder = "{df}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]\n'
          f"\tlineageTag: {guid('expression', 'DataFolder')}\n\n"
          "\tannotation PBI_ResultType = Text\n\n")

    # ---- relationships ----
    rels = [
        ("Sales", "UPC", "Product", "UPC"),
        ("Sales", "Store ID", "Store", "Store ID"),
        ("Sales", "Week ID", "Calendar", "Week ID"),
        ("Product", "Brand", "Brand", "Brand"),
    ]
    rel_txt = ""
    for ft, fc, tt, tc in rels:
        rel_txt += f"relationship {guid('rel', ft, fc, tt, tc)}\n"
        rel_txt += f"\tfromColumn: {q(ft)}.{q(fc)}\n"
        rel_txt += f"\ttoColumn: {q(tt)}.{q(tc)}\n\n"
    write(d / "relationships.tmdl", rel_txt)

    t = d / "tables"
    # ---- Sales (fact) ----
    write(t / "Sales.tmdl", tmdl_table(
        "Sales",
        "Weekly store x UPC sales of ready-to-eat cereal at Dominick's Finer Foods (1989-1997). One row per store, UPC and week with a sale. Source: Kilts Center, Chicago Booth.",
        [
            col("Store ID", "store_id", "int64", fmt="0", hidden=True, desc="Foreign key to Store."),
            col("UPC", "upc", "int64", fmt="0", hidden=True, desc="Foreign key to Product (UPC without check digit, as in the Kilts files)."),
            col("Week ID", "week_id", "int64", fmt="0", hidden=True, desc="Foreign key to Calendar (Dominick's week number, week 1 = 14 Sep 1989)."),
            col("Units", "units", "int64", fmt="#,0", summarize="sum", desc="Packages sold in the week (MOVE)."),
            # double, not fixed-decimal: Currency / Double keeps 4 decimals and truncates unit prices (verified)
            col("Revenue", "revenue", "double", fmt="\\$#,0.00;-\\$#,0.00;\\$#,0.00", summarize="sum", desc="Retail dollar sales = PRICE x MOVE / QTY (bundle prices unwound)."),
            col("Volume (oz)", "volume_oz", "double", fmt="#,0.0", summarize="sum", desc="Units x pack size in ounces."),
            col("Pack Price", "pack_price", "double", fmt="\\$#,0.00;-\\$#,0.00;\\$#,0.00", summarize="none", desc="Shelf price of one package that week (PRICE / QTY). Use the Avg Pack Price measure to aggregate."),
            col("Promo", "promo", "int64", fmt="0", summarize="none", desc="1 if Dominick's recorded a promotion code (B bonus buy, C coupon, S price cut) that week, else 0. Promotions are under-recorded in the source."),
        ],
        [],
        "m",
        m_csv_partition("fact_sales.csv", [
            ("store_id", "Int64.Type"), ("upc", "Int64.Type"), ("week_id", "Int64.Type"), ("units", "Int64.Type"),
            ("revenue", "type number"), ("volume_oz", "type number"), ("pack_price", "type number"), ("promo", "Int64.Type"),
        ], 8),
    ))
    # ---- Product ----
    write(t / "Product.tmdl", tmdl_table(
        "Product",
        "One row per cereal UPC kept in the analysis (441 shelf packs; trial sizes, variety packs and non-cereal items excluded).",
        [
            col("UPC", "upc", "int64", fmt="0", key=True, desc="Universal Product Code (Kilts 10-digit form)."),
            col("Product", "product", "string", desc="Description + pack size, e.g. 'Cheerios 15 oz'."),
            col("Description", "description", "string", desc="Dominick's item description (truncated to 20 characters in the source)."),
            col("Brand", "brand", "string", desc="Brand owner / manufacturer brand: Kellogg's, General Mills, Post, Quaker, Ralston, Nabisco, Private Label (Dominick's), Malt-O-Meal, Other."),
            col("Product Line", "product_line", "string", desc="Sub-brand / product line (e.g. Cheerios, Frosted Flakes, Chex)."),
            col("Pack Size (oz)", "pack_oz", "double", fmt="0.0#", desc="Net weight per package in ounces, parsed from the SIZE field."),
            col("Pack Size (g)", "pack_g", "double", fmt="#,0", desc="Net weight per package in grams (1 oz = 28.35 g)."),
            col("Pack Tier", "pack_tier", "string", desc="Pack-size tier: 1 Small <12 oz, 2 Medium 12-16, 3 Large 16-20, 4 Family 20-30, 5 Club 30+ oz."),
            col("Pack Label", "pack_label", "string", sort_by="Pack Size (oz)", desc="Pack size as text (e.g. '15 oz'), sorted by ounces."),
            col("Private Label", "is_private_label", "boolean", desc="TRUE for Dominick's / Heritage House store brands."),
        ],
        [],
        "m",
        m_csv_partition("dim_product.csv", [
            ("upc", "Int64.Type"), ("product", "type text"), ("description", "type text"), ("brand", "type text"),
            ("product_line", "type text"), ("pack_oz", "type number"), ("pack_g", "type number"), ("pack_tier", "type text"),
            ("pack_label", "type text"), ("is_private_label", "type logical"),
        ], 10),
    ))
    # ---- Store ----
    write(t / "Store.tmdl", tmdl_table(
        "Store",
        "Dominick's stores in the Chicago area with the chain's pricing zone and price tier (High / Medium / Low = 'Cub fighter') from the Kilts demographics file.",
        [
            col("Store ID", "store_id", "int64", fmt="0", key=True, desc="Dominick's store number."),
            col("Store", "store_name", "string", desc="Store number and city."),
            col("City", "city", "string"),
            col("ZIP", "zip", "string"),
            col("Zone", "zone", "int64", fmt="0", desc="Dominick's pricing zone (0 = unknown)."),
            col("Price Tier", "price_tier", "string", desc="Chain price tier the store belongs to: High, Medium, Low (Cub-fighter stores near Cub Foods) or Unknown."),
            col("Store Cluster", "store_cluster", "string", desc="Dominick's demographic store cluster (A-D)."),
            col("Log Median Income", "log_median_income", "double", fmt="0.00", desc="Log of median household income in the store's trade area (1990 census)."),
            col("Weekly Volume (k)", "weekly_volume_k", "double", fmt="#,0", desc="Average weekly store sales volume ($000)."),
        ],
        [],
        "m",
        m_csv_partition("dim_store.csv", [
            ("store_id", "Int64.Type"), ("store_name", "type text"), ("city", "type text"), ("zip", "type text"), ("zone", "Int64.Type"),
            ("price_tier", "type text"), ("store_cluster", "type text"), ("log_median_income", "type number"), ("weekly_volume_k", "type number"),
        ], 9),
    ))
    # ---- Calendar (weekly) ----
    write(t / "Calendar.tmdl", tmdl_table(
        "Calendar",
        "Weekly calendar: one row per Dominick's week with sales (week 1 starts 14 Sep 1989). 32 chain-wide gap weeks in the source are absent.",
        [
            col("Week ID", "week_id", "int64", fmt="0", key=True, desc="Dominick's week number."),
            col("Week Start", "week_start", "dateTime", fmt="yyyy-mm-dd", desc="Thursday the week starts on.", extra_annotations=["UnderlyingDateTimeDataType = Date"]),
            col("Week End", "week_end", "dateTime", fmt="yyyy-mm-dd", extra_annotations=["UnderlyingDateTimeDataType = Date"]),
            col("Year", "year", "int64", fmt="0"),
            col("Quarter", "quarter", "string"),
            col("Year Quarter", "year_quarter", "string", desc="e.g. '1991 Q3' - sorts naturally."),
            col("Month Number", "month_num", "int64", fmt="0", hidden=True),
            col("Month", "month", "string", sort_by="Month Number"),
            col("Year Month", "year_month", "string", sort_by="Year Month Sort", desc="e.g. '1991-07'."),
            col("Year Month Sort", "year_month_sort", "int64", fmt="0", hidden=True),
        ],
        [],
        "m",
        m_csv_partition("dim_week.csv", [
            ("week_id", "Int64.Type"), ("week_start", "type date"), ("week_end", "type date"), ("year", "Int64.Type"), ("quarter", "type text"),
            ("year_quarter", "type text"), ("month_num", "Int64.Type"), ("month", "type text"), ("year_month", "type text"), ("year_month_sort", "Int64.Type"),
        ], 10),
    ))
    # ---- Brand (elasticity results) ----
    write(t / "Brand.tmdl", tmdl_table(
        "Brand",
        "Own-price elasticity per brand estimated in prep.py: ln(units) = e ln(price) + b promo + UPC x store FE + week FE, SE clustered by UPC x store. Includes a 'Category (all brands)' reference row.",
        [
            col("Brand", "brand", "string", key=True),
            col("Elasticity", "elasticity", "double", fmt="0.00", desc="Own-price elasticity of weekly units (log-log coefficient). -2.0 means +1% price -> -2% units."),
            col("Std Error", "std_error", "double", fmt="0.000", desc="Cluster-robust standard error (clusters = UPC x store)."),
            col("CI Low (95%)", "ci_low", "double", fmt="0.00"),
            col("CI High (95%)", "ci_high", "double", fmt="0.00"),
            col("Promo Lift Coef", "promo_lift_coef", "double", fmt="0.00", desc="Coefficient on the promo flag (log points of extra units in a recorded promo week, holding price constant)."),
            col("R2 Within", "r2_within", "double", fmt="0.000", desc="Within R-squared after removing UPC x store and week fixed effects."),
            col("N Obs", "n_obs", "int64", fmt="#,0", desc="Store-UPC-week observations used."),
            col("N UPC x Store", "n_units", "int64", fmt="#,0", desc="Number of UPC x store panels (clusters)."),
            col("N UPCs", "n_upcs", "int64", fmt="#,0"),
            col("N Stores", "n_stores", "int64", fmt="#,0"),
            col("Revenue Share", "revenue_share", "double", fmt="0.0%", desc="Share of category revenue over the full period."),
            col("Flag", "flag", "string", desc="Plausibility check: OK if elasticity is within -5 to -0.3."),
            col("Method", "method", "string"),
            col("Elasticity (no promo control)", "elasticity_no_promo_control", "double", fmt="0.00", desc="Robustness: same fixed effects, promo flag dropped (top 5 brands only)."),
        ],
        [],
        "m",
        m_csv_partition("dim_brand_elasticity.csv", [
            ("brand", "type text"), ("elasticity", "type number"), ("std_error", "type number"), ("ci_low", "type number"), ("ci_high", "type number"),
            ("promo_lift_coef", "type number"), ("r2_within", "type number"), ("n_obs", "Int64.Type"), ("n_units", "Int64.Type"), ("n_upcs", "Int64.Type"),
            ("n_stores", "Int64.Type"), ("revenue_share", "type number"), ("flag", "type text"), ("method", "type text"), ("elasticity_no_promo_control", "type number"),
        ], 15),
    ))
    # ---- What-if parameter table ----
    # integer series (-20..20) instead of GENERATESERIES(-0.2, 0.2, 0.01): the floating-point step drops an endpoint (40 rows, verified)
    whatif_cols = [
        col("Price Change %", "[Value]", "int64", fmt='0"%"', desc="What-if parameter: list-price change in percent applied to the selected brands (-20 to +20, 1-point steps).",
            extended=("ParameterMetadata", {"version": 0})),
    ]
    whatif_txt = tmdl_table(
        "Price Change %",
        "What-if parameter table (GENERATESERIES). Drive it with the single-value slicer on the report.",
        whatif_cols,
        [measure("Price Change % Value", "SELECTEDVALUE ( 'Price Change %'[Price Change %], 0 ) / 100", fmt="0%",
                 desc="Selected price change from the what-if slicer as a fraction (5% -> 0.05); 0 when nothing is selected.")],
        "calculated",
        "GENERATESERIES ( -20, 20, 1 )",
    )
    # NOTE: do not mark this column isNameInferred - the engine would then call it "Value" and the
    # SELECTEDVALUE measure could not bind to 'Price Change %'[Price Change %] (verified against the local AS instance).
    write(t / "Price Change %.tmdl", whatif_txt)

    # ---- Measures table ----
    P = "'Pricing Measures'"
    measures = [
        # --- base
        measure("Revenue", "SUM ( Sales[Revenue] )", fmt="\\$#,0;-\\$#,0;\\$#,0", folder="1. Base",
                desc="Retail dollar sales in the current filter context."),
        measure("Units", "SUM ( Sales[Units] )", fmt="#,0", folder="1. Base", desc="Packages sold."),
        measure("Volume (oz)", "SUM ( Sales[Volume (oz)] )", fmt="#,0", folder="1. Base", desc="Ounces sold (units x pack size)."),
        measure("Volume (kg)", "[Volume (oz)] * 0.028349523125", fmt="#,0", folder="1. Base", desc="Kilograms sold."),
        measure("Stores Selling", "DISTINCTCOUNT ( Sales[Store ID] )", fmt="#,0", folder="1. Base", desc="Stores with at least one sale in context."),
        measure("UPCs Selling", "DISTINCTCOUNT ( Sales[UPC] )", fmt="#,0", folder="1. Base", desc="Distinct UPCs with at least one sale in context."),
        # --- price architecture
        measure("Avg Pack Price", "DIVIDE ( [Revenue], [Units] )", fmt="\\$#,0.00;-\\$#,0.00;\\$#,0.00", folder="2. Price architecture",
                desc="Revenue-weighted average shelf price per package."),
        measure("Avg Pack Size (oz)", "DIVIDE ( [Volume (oz)], [Units] )", fmt="0.0", folder="2. Price architecture",
                desc="Units-weighted average pack size in ounces (x-axis of the price-architecture curve)."),
        measure("Price per oz", "DIVIDE ( [Revenue], [Volume (oz)] )", fmt="\\$#,0.000;-\\$#,0.000;\\$#,0.000", folder="2. Price architecture",
                desc="Volume-weighted unit price per ounce = revenue / ounces sold."),
        measure("Price per 100g", "DIVIDE ( [Revenue], [Volume (oz)] * 28.349523125 ) * 100", fmt="\\$#,0.000;-\\$#,0.000;\\$#,0.000", folder="2. Price architecture",
                desc="Volume-weighted unit price per 100 g = revenue / grams sold x 100. The core price-architecture metric."),
        # --- monitoring
        measure("Category Price per 100g",
                "CALCULATE ( [Price per 100g], REMOVEFILTERS ( 'Product' ), REMOVEFILTERS ( 'Brand' ) )",
                fmt="\\$#,0.000;-\\$#,0.000;\\$#,0.000", folder="3. Price monitoring",
                desc="Category benchmark: price per 100 g across ALL brands and packs, keeping the store and period filters."),
        measure("Brand Price Index", "DIVIDE ( [Price per 100g], [Category Price per 100g] ) * 100", fmt="0.0", folder="3. Price monitoring",
                desc="Price per 100 g of the selected brand(s) relative to the category average = 100, within the same stores and weeks."),
        measure("Price Premium %", "DIVIDE ( [Price per 100g], [Category Price per 100g] ) - 1", fmt="+0.0%;-0.0%;0.0%", folder="3. Price monitoring",
                desc="Brand Price Index expressed as a premium (+) or discount (-) vs the category."),
        measure("Promo Share of Units", "DIVIDE ( CALCULATE ( [Units], Sales[Promo] = 1 ), [Units] )", fmt="0.0%", folder="3. Price monitoring",
                desc="Share of packages sold in weeks with a recorded promotion code."),
        measure("Revenue Share", "DIVIDE ( [Revenue], CALCULATE ( [Revenue], REMOVEFILTERS ( 'Product' ), REMOVEFILTERS ( 'Brand' ) ) )", fmt="0.0%", folder="3. Price monitoring",
                desc="Share of category revenue in the selected stores and weeks."),
        # --- what-if
        measure("Elasticity (revenue-weighted)",
                "DIVIDE (\n    SUMX ( VALUES ( 'Brand'[Brand] ), [Revenue] * CALCULATE ( MIN ( 'Brand'[Elasticity] ) ) ),\n    [Revenue]\n)",
                fmt="0.00", folder="4. Price increase what-if",
                desc="Own-price elasticity of the selection; brands are weighted by their revenue in context."),
        measure("Elasticity (selected)",
                "IF ( HASONEVALUE ( 'Brand'[Brand] ), MIN ( 'Brand'[Elasticity] ), [Elasticity (revenue-weighted)] )",
                fmt="0.00", folder="4. Price increase what-if",
                desc="Elasticity used by the simulator: the brand's own estimate when one brand is in context, otherwise the revenue-weighted mix."),
        measure("Simulated Units",
                "SUMX (\n    VALUES ( 'Brand'[Brand] ),\n    VAR e = CALCULATE ( MIN ( 'Brand'[Elasticity] ) )\n    RETURN [Units] * POWER ( 1 + [Price Change % Value], e )\n)",
                fmt="#,0", folder="4. Price increase what-if",
                desc="Units after the price change, brand by brand: Units x (1 + change)^elasticity (constant-elasticity demand)."),
        measure("Simulated Revenue",
                "SUMX (\n    VALUES ( 'Brand'[Brand] ),\n    VAR e = CALCULATE ( MIN ( 'Brand'[Elasticity] ) )\n    RETURN [Revenue] * POWER ( 1 + [Price Change % Value], 1 + e )\n)",
                fmt="\\$#,0;-\\$#,0;\\$#,0", folder="4. Price increase what-if",
                desc="Revenue after the price change: Revenue x (1 + change)^(1 + elasticity)."),
        measure("Volume Impact %", "DIVIDE ( [Simulated Units], [Units] ) - 1", fmt="+0.0%;-0.0%;0.0%", folder="4. Price increase what-if",
                desc="Change in units from the simulated price change."),
        measure("Revenue Impact %", "DIVIDE ( [Simulated Revenue], [Revenue] ) - 1", fmt="+0.0%;-0.0%;0.0%", folder="4. Price increase what-if",
                desc="Change in revenue from the simulated price change (positive only when |elasticity| < 1)."),
        measure("Revenue Impact $", "[Simulated Revenue] - [Revenue]", fmt="\\$#,0;-\\$#,0;\\$#,0", folder="4. Price increase what-if",
                desc="Dollar change in revenue over the selected period from the simulated price change."),
        measure("Breakeven Volume Change %", "DIVIDE ( -[Price Change % Value], 1 + [Price Change % Value] )", fmt="+0.0%;-0.0%;0.0%", folder="4. Price increase what-if",
                desc="Volume change that would leave revenue unchanged at the selected price change: -p / (1 + p). Compare with Volume Impact %."),
    ]
    mt = (
        "/// Home table for all DAX measures (no data rows).\n"
        "table 'Pricing Measures'\n"
        f"\tlineageTag: {guid('table', 'Pricing Measures')}\n\n"
        + "".join(tmdl_measure("Pricing Measures", m) for m in measures)
        + "\tcolumn Value\n\t\tisHidden\n\t\tformatString: 0\n"
        + f"\t\tlineageTag: {guid('Pricing Measures', 'col', 'Value')}\n\t\tsummarizeBy: none\n\t\tisNameInferred\n\t\tsourceColumn: [Value]\n\n"
        + "\t\tannotation SummarizationSetBy = Automatic\n\n"
        + "\tpartition 'Pricing Measures' = calculated\n\t\tmode: import\n\t\tsource = {0}\n\n"
    )
    write(t / "Pricing Measures.tmdl", mt)


# =====================================================================================
# PBIR report
# =====================================================================================
def lit(v) -> dict:
    """Literal expression wrapper: str -> 'text', bool -> true/false, numbers -> 12D."""
    if isinstance(v, bool):
        s = "true" if v else "false"
    elif isinstance(v, (int, float)):
        s = f"{v}D"
    else:
        s = "'" + str(v).replace("'", "''") + "'"
    return {"expr": {"Literal": {"Value": s}}}


def color(hexstr: str) -> dict:
    return {"solid": {"color": lit(hexstr)}}


def column_ref(table: str, column: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": column}}


def measure_ref(table: str, name: str) -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}}


def proj(field: dict, table: str, name: str, display: str | None = None, active: bool = False) -> dict:
    p = {"field": field, "queryRef": f"{table}.{name}", "nativeQueryRef": display or name}
    if active:
        p["active"] = True
    if display and display != name:
        p["displayName"] = display
    return p


def C(table, column, display=None, active=False):
    return proj(column_ref(table, column), table, column, display, active)


def M(name, display=None):
    return proj(measure_ref("Pricing Measures", name), "Pricing Measures", name, display)


def props(**kw) -> list[dict]:
    return [{"properties": kw}]


def visual(name: str, vtype: str, pos: tuple, roles: dict | None, title: str | None = None, objects: dict | None = None,
           vco: dict | None = None, sort: list | None = None, subtitle: str | None = None, extra: dict | None = None) -> dict:
    x, y, w, h = pos
    v: dict = {"visualType": vtype}
    if roles is not None:
        v["query"] = {"queryState": {role: {"projections": ps} for role, ps in roles.items()}}
        if sort:
            v["query"]["sortDefinition"] = {"sort": sort}
    if objects:
        v["objects"] = objects
    vco = dict(vco or {})
    if title:
        vco["title"] = props(show=lit(True), text=lit(title), fontSize=lit(11), bold=lit(True))
    if subtitle:
        vco["subTitle"] = props(show=lit(True), text=lit(subtitle), fontSize=lit(9))
    if vco:
        v["visualContainerObjects"] = vco
    v["drillFilterOtherVisuals"] = True
    if extra:
        v.update(extra)
    return {
        "$schema": S_VISUAL,
        "name": hid("visual", name),
        "position": {"x": x, "y": y, "z": 1000, "height": h, "width": w, "tabOrder": 1000},
        "visual": v,
    }


def textbox(name: str, pos: tuple, runs: list[list[tuple[str, dict]]]) -> dict:
    x, y, w, h = pos
    paragraphs = [{"textRuns": [{"value": txt, "textStyle": style} for txt, style in para]} for para in runs]
    return {
        "$schema": S_VISUAL,
        "name": hid("visual", name),
        "position": {"x": x, "y": y, "z": 0, "height": h, "width": w, "tabOrder": 0},
        "visual": {
            "visualType": "textbox",
            "objects": {"general": [{"properties": {"paragraphs": paragraphs}}]},
            "visualContainerObjects": {"background": props(show=lit(False)), "border": props(show=lit(False)), "title": props(show=lit(False))},
            "drillFilterOtherVisuals": True,
        },
    }


def slicer(name: str, pos: tuple, table: str, column: str, mode: str, header: str, extra_general: dict | None = None,
           default_value: str | None = None) -> dict:
    objects = {
        "data": props(mode=lit(mode)),
        "header": props(show=lit(True), text=lit(header), fontSize=lit(9), bold=lit(True)),
        "items": props(fontSize=lit(9)),
    }
    if default_value is not None:
        # pre-selected value (what the slicer opens with); raw literal such as "5L" for an integer column.
        # Used with a single-select list/dropdown: the single-value slider does not display a persisted default.
        objects["selection"] = props(singleSelect=lit(True))
        objects["general"] = props(filter={"filter": {
            "Version": 2,
            "From": [{"Name": "t", "Entity": table, "Type": 0}],
            "Where": [{"Condition": {"In": {
                "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "t"}}, "Property": column}}],
                "Values": [[{"Literal": {"Value": default_value}}]],
            }}}],
        }})
    if extra_general:
        objects.setdefault("general", [{"properties": {}}])[0]["properties"].update(extra_general)
    return visual(name, "slicer", pos, {"Values": [C(table, column, active=True)]}, objects=objects,
                  vco={"title": props(show=lit(False))})


def card(name: str, pos: tuple, meas: str, label: str) -> dict:
    return visual(name, "card", pos, {"Values": [M(meas, label)]},
                  objects={"labels": props(fontSize=lit(18)), "categoryLabels": props(show=lit(True), fontSize=lit(9))},
                  vco={"title": props(show=lit(False))})


def brand_filter(brands: list[str]) -> dict:
    """Visual-level categorical filter: Product[Brand] IN (brands)."""
    return {"filters": [{
        "name": hid("filter", *brands),
        "field": column_ref("Product", "Brand"),
        "type": "Categorical",
        "filter": {
            "Version": 2,
            "From": [{"Name": "p", "Entity": "Product", "Type": 0}],
            "Where": [{"Condition": {"In": {
                "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "p"}}, "Property": "Brand"}}],
                "Values": [[{"Literal": {"Value": "'" + b.replace("'", "''") + "'"}}] for b in brands],
            }}}],
        },
    }]}


def build_report(out: Path, theme_src: Path) -> None:
    rd = out / REPORT_DIR
    write_json(rd / ".platform", {
        "$schema": S_PLATFORM,
        "metadata": {"type": "Report", "displayName": PROJECT},
        "config": {"version": "2.0", "logicalId": guid("platform", "report")},
    })
    write_json(rd / "definition.pbir", {"$schema": S_PBIR, "version": "4.0", "datasetReference": {"byPath": {"path": f"../{MODEL_DIR}"}}})
    d = rd / "definition"
    write_json(d / "version.json", {"$schema": S_VERSION, "version": "2.0.0"})
    write_json(d / "report.json", {
        "$schema": S_REPORT,
        "themeCollection": {"baseTheme": {"name": BASE_THEME, "reportVersionAtImport": {"visual": "2.9.0", "report": "3.3.0", "page": "2.1.0"}, "type": "SharedResources"}},
        "resourcePackages": [{"name": "SharedResources", "type": "SharedResources", "items": [{"name": BASE_THEME, "path": f"BaseThemes/{BASE_THEME}.json", "type": "BaseTheme"}]}],
        "objects": {"outspacePane": props(visible=lit(False), expanded=lit(False))},
        "settings": {"useStylableVisualContainerHeader": True, "defaultDrillFilterOtherVisuals": True, "allowChangeFilterTypes": True,
                     "useEnhancedTooltips": True, "useDefaultAggregateDisplayName": True},
        "annotations": [{"name": "readme", "value": "Generated by build_pbip.py - Dominick's RTE cereal pricing portfolio project."}],
    })
    theme_dst = rd / "StaticResources" / "SharedResources" / "BaseThemes" / f"{BASE_THEME}.json"
    theme_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(theme_src, theme_dst)

    page_name = hid("page", "Pricing Dashboard")
    write_json(d / "pages" / "pages.json", {"$schema": S_PAGES, "pageOrder": [page_name], "activePageName": page_name})
    pd_ = d / "pages" / "PricingDashboard"
    write_json(pd_ / "page.json", {
        "$schema": S_PAGE, "name": page_name, "displayName": "Pricing Dashboard", "displayOption": "FitToPage",
        "height": PAGE_H, "width": PAGE_W,
        "objects": {"background": props(color=color("#F3F4F6"), transparency=lit(0))},
    })

    visuals: dict[str, dict] = {}
    # ---------- header ----------
    visuals["title"] = textbox("title", (16, 6, 900, 50), [
        [("Ready-to-Eat Cereal: Price Architecture, Price Monitoring & Price-Increase Simulator",
          {"fontSize": "14pt", "fontWeight": "bold", "color": "#1F2937"})],
        [("Dominick's Finer Foods (Chicago), 93 stores, 441 UPCs, Sep 1989 - May 1997  |  Source: Kilts Center, Chicago Booth  |  Portfolio project (public academic data)",
          {"fontSize": "9pt", "color": "#6B7280"})],
    ])
    visuals["slicer_brand"] = slicer("slicer_brand", (940, 6, 200, 54), "Product", "Brand", "Dropdown", "Brand")
    visuals["slicer_tier"] = slicer("slicer_tier", (1160, 6, 200, 54), "Store", "Price Tier", "Dropdown", "Store price tier")
    visuals["slicer_year"] = slicer("slicer_year", (1380, 6, 204, 54), "Calendar", "Year", "Dropdown", "Year")

    # ---------- KPI cards ----------
    visuals["card_revenue"] = card("card_revenue", (16, 66, 388, 64), "Revenue", "Revenue")
    visuals["card_units"] = card("card_units", (420, 66, 388, 64), "Units", "Packages sold")
    visuals["card_p100"] = card("card_p100", (824, 66, 388, 64), "Price per 100g", "Avg price per 100 g")
    visuals["card_promo"] = card("card_promo", (1228, 66, 356, 64), "Promo Share of Units", "Promo share of units")

    # ---------- Module 1: price architecture ----------
    visuals["m1_scatter"] = visual(
        "m1_scatter", "scatterChart", (16, 138, 700, 200),
        {"Category": [C("Product", "Product", active=True)], "Series": [C("Product", "Brand")],
         "X": [M("Avg Pack Size (oz)", "Pack size (oz)")], "Y": [M("Price per 100g", "Price per 100 g")], "Size": [M("Revenue")]},
        title="1 | Price architecture: price per 100 g vs pack size (bubble = revenue, one bubble per UPC)",
        objects={"legend": props(show=lit(True), position=lit("Right"), showTitle=lit(False), fontSize=lit(8)),
                 "categoryAxis": props(showAxisTitle=lit(True)), "valueAxis": props(showAxisTitle=lit(True), start=lit(0)),
                 "bubbles": props(bubbleSize=lit(-10)), "markers": props(transparency=lit(25))},
    )
    visuals["m1_matrix"] = visual(
        "m1_matrix", "pivotTable", (732, 138, 852, 200),
        {"Rows": [C("Product", "Brand", active=True)], "Columns": [C("Product", "Pack Tier", active=True)],
         "Values": [M("Price per 100g", "$ / 100 g")]},
        title="1 | Price per 100 g by brand x pack-size tier (blank = not sold)",
        objects={"columnHeaders": props(fontSize=lit(8), wordWrap=lit(False), autoSizeColumnWidth=lit(False)),
                 "rowHeaders": props(fontSize=lit(8)),
                 "values": props(fontSize=lit(8)), "subTotals": props(rowSubtotals=lit(True), columnSubtotals=lit(True)),
                 "grid": props(rowPadding=lit(0)),
                 "columnWidth": [{"properties": {"value": lit(118)}, "selector": {"metadata": "Pricing Measures.Price per 100g"}}]},
        sort=[{"field": measure_ref("Pricing Measures", "Price per 100g"), "direction": "Descending"}],
    )

    # ---------- Module 2: price monitoring ----------
    visuals["m2_line"] = visual(
        "m2_line", "lineChart", (16, 346, 700, 154),
        {"Category": [C("Calendar", "Year", active=True)], "Series": [C("Product", "Brand")], "Y": [M("Brand Price Index", "Price index (category = 100)")]},
        title="2 | Brand price index vs category average (= 100) by year - top 4 brands and private label",
        objects={"legend": props(show=lit(True), position=lit("Top"), showTitle=lit(False)),
                 "categoryAxis": props(showAxisTitle=lit(False)), "valueAxis": props(showAxisTitle=lit(False)),
                 "lineStyles": props(strokeWidth=lit(2)),
                 "y1AxisReferenceLine": [{"properties": {"show": lit(True), "value": lit(100), "style": lit("dashed"), "lineColor": color("#6B7280"),
                                                         "transparency": lit(0), "dataLabelShow": lit(True), "dataLabelText": lit("Value")},
                                          "selector": {"id": "0"}}]},
    )
    visuals["m2_bar"] = visual(
        "m2_bar", "clusteredColumnChart", (732, 346, 852, 154),
        {"Category": [C("Product", "Brand", active=True)], "Series": [C("Store", "Price Tier")], "Y": [M("Price per 100g", "Price per 100 g")]},
        title="2 | Price per 100 g by brand and store price tier (High / Medium / Low zone)",
        objects={"legend": props(show=lit(True), position=lit("Top"), showTitle=lit(True), titleText=lit("Store tier")),
                 "categoryAxis": props(showAxisTitle=lit(False)), "valueAxis": props(showAxisTitle=lit(False), start=lit(0)),
                 "labels": props(show=lit(False))},
        sort=[{"field": measure_ref("Pricing Measures", "Price per 100g"), "direction": "Descending"}],
    )

    # ---------- Module 3: what-if ----------
    visuals["m3_slicer"] = slicer("m3_slicer", (16, 508, 230, 78), "Price Change %", "Price Change %", "Dropdown", "3 | Price change % (what-if)",
                                  default_value="5L")   # single-select dropdown, opens at +5% so the impact cards show numbers immediately
    visuals["m3_card_e"] = card("m3_card_e", (16, 594, 230, 136), "Elasticity (selected)", "Own-price elasticity (selection)")
    visuals["m3_card_vol"] = card("m3_card_vol", (262, 508, 170, 66), "Volume Impact %", "Volume impact")
    visuals["m3_card_rev"] = card("m3_card_rev", (444, 508, 170, 66), "Revenue Impact %", "Revenue impact")
    visuals["m3_card_usd"] = card("m3_card_usd", (626, 508, 170, 66), "Revenue Impact $", "Revenue impact ($, period)")
    visuals["m3_card_be"] = card("m3_card_be", (812, 508, 170, 66), "Breakeven Volume Change %", "Break-even volume change")
    visuals["m3_bar"] = visual(
        "m3_bar", "clusteredColumnChart", (262, 582, 888, 148),
        {"Category": [C("Product", "Brand", active=True)], "Y": [M("Revenue Impact $", "Revenue impact ($)")]},
        title="3 | Revenue impact ($M) by brand at the selected price change",
        objects={"legend": props(show=lit(False)),
                 "categoryAxis": props(showAxisTitle=lit(False), fontSize=lit(8), innerPadding=lit(30)),
                 "valueAxis": props(show=lit(False), showAxisTitle=lit(False)),
                 "labels": props(show=lit(True), fontSize=lit(8), labelDisplayUnits=lit(1000000), labelPrecision={"expr": {"Literal": {"Value": "1L"}}})},
        sort=[{"field": measure_ref("Pricing Measures", "Revenue Impact $"), "direction": "Ascending"}],
    )
    visuals["m3_table"] = visual(
        "m3_table", "tableEx", (1164, 508, 420, 222),
        {"Values": [C("Brand", "Brand"), C("Brand", "Elasticity", "e"), C("Brand", "CI Low (95%)", "CI low"), C("Brand", "CI High (95%)", "CI high"),
                    C("Brand", "R2 Within", "R2"), C("Brand", "N Obs", "n")]},
        title="3 | Elasticity by brand (log-log, UPC x store + week fixed effects)",
        objects={"columnHeaders": props(fontSize=lit(8), wordWrap=lit(False)), "values": props(fontSize=lit(8)), "grid": props(rowPadding=lit(1)),
                 "total": props(totals=lit(False))},
        sort=[{"field": column_ref("Brand", "Revenue Share"), "direction": "Descending"}],
    )

    # module-3 bar chart: baseline revenue as tooltip context
    visuals["m3_bar"]["visual"]["query"]["queryState"]["Tooltips"] = {"projections": [M("Revenue")]}
    # table sorts by Revenue Share -> include it (hidden) too
    visuals["m3_table"]["visual"]["query"]["queryState"]["Values"]["projections"].append({**C("Brand", "Revenue Share", "share"), "hidden": True})
    # line chart: only the four largest brands and private label (visual-level filter)
    visuals["m2_line"]["filterConfig"] = brand_filter(["Kellogg's", "General Mills", "Post", "Quaker", "Private Label"])

    z = 0
    for folder, v in visuals.items():
        z += 1
        v["position"]["z"] = z * 100
        v["position"]["tabOrder"] = z * 100
        write_json(pd_ / "visuals" / folder / "visual.json", v)


def build_pbip_file(out: Path) -> None:
    write_json(out / f"{PROJECT}.pbip", {
        "$schema": S_PBIP, "version": "1.0",
        "artifacts": [{"report": {"path": REPORT_DIR}}],
        "settings": {"enableAutoRecovery": True},
    })
    write(out / ".gitignore", "**/.pbi/localSettings.json\n**/.pbi/cache.abf\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    # default is a placeholder so the committed PBIP carries no machine-specific path;
    # pass --data-folder "<abs path>\output" (or set the parameter in Desktop) to point at real data
    ap.add_argument("--data-folder", default=r"C:\path\to\output")
    ap.add_argument("--out", default=str(ROOT / "pbip"))
    ap.add_argument("--theme", default=str(ROOT / "assets" / f"{BASE_THEME}.json"))
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        try:
            shutil.rmtree(out)
        except PermissionError:
            print("warning: could not fully delete the old pbip folder (is it open in Power BI Desktop?); overwriting in place")
    out.mkdir(parents=True, exist_ok=True)
    build_model(out, a.data_folder)
    build_report(out, Path(a.theme))
    build_pbip_file(out)
    n = sum(1 for _ in out.rglob("*") if _.is_file())
    print(f"PBIP written to {out} ({n} files). DataFolder = {a.data_folder}")


if __name__ == "__main__":
    main()
