# Decision log

Chronological log of the judgement calls made while building the project. Each entry: decision, why, alternatives considered.

## D1. Dataset: Dominick's Finer Foods (Kilts Center, Chicago Booth), not Dunnhumby "The Complete Journey"
- **Why:** Dominick's is downloadable without a login (CSV links on the Kilts page), has real brand names in the UPC description, a `SIZE` field for pack size, 93 stores, 399 weeks, and store-level price zones. Dunnhumby's `brand` field only distinguishes National vs Private label, which is too weak for brand price architecture, competitor monitoring or per-brand elasticity.
- **Licence:** "These data are for academic research purposes only" and users must acknowledge the Kilts Center for Marketing at the University of Chicago Booth School of Business. No explicit redistribution clause was found, so the raw files are **not** committed (`data/raw/` is git-ignored). The row-level derived fact table (`output/fact_sales.csv`, 185 MB) is also git-ignored; the small dimension CSVs and aggregated metrics are kept. Anyone cloning the repo re-creates the data with `prep.py` from the public links in the README.
- **Caveat:** data is 1989-1997 (pre-euro, pre-mobile). This is a methods portfolio, not a market study.

## D2. Category: ready-to-eat cereal (`cer`), not front-end candies (`fec`)
- Candy was considered, but 301 of 505 candy UPCs carry `SIZE = "1 CT"` with no weight, so price per 100 g (the core metric of this dashboard) cannot be computed for most items. Cereal has 490 UPCs with weights in oz, 6 national manufacturers plus private label, and 5+ pack-size tiers per major brand.

## D3. "Brand" = brand owner / manufacturer brand
- Brand is mapped from the UPC company prefix (16000 = General Mills, 38000 = Kellogg's, 43000 = Post, 30000 = Quaker, 13130 = Nabisco, 17800/79166 = Ralston, 38281 = Dominick's private label, 42400 = Malt-O-Meal) with description overrides (e.g. `NAB*` items sold under Post's prefix after 1993 stay Nabisco). Sub-brands (Cheerios, Frosted Flakes, Chex ...) are kept as `Product Line` for drill-down.
- This gives 9 brands (4+ required) with enough UPC x store x week observations for per-brand regressions. Elasticity at sub-brand level is possible but was not needed for the dashboard.

## D4. Rows dropped (all counts in `output/data_quality_report.md`)
- `OK = 0` rows (Kilts' own "suspect" flag): 141,285.
- Zero units or zero price (no sale that week, not a real observation): 1,753,521.
- Excluded UPCs: non-cereal (Pop-Tarts, T-shirt, magazine shipper, wheat germ, hot cereal), variety/fun packs, trial sizes < 5 oz, and 3 UPCs whose SIZE could not be parsed (incl. a top-30 Kellogg's Crispix UPC with `SIZE = "end"`). Sizes are never guessed. 131,321 rows.
- Price outliers vs the UPC's own median package price (x > 2.5 or x < 0.35): 531 rows (0.012%). Promotional cuts are rarely deeper than 50%, so this catches keying errors without removing promotions.
- Result: 4,575,924 of 6,602,582 raw rows (69.3%). Promo weeks are kept (they are the price variation).

## D5. Grain: store x UPC x week kept in the fact table
- Alternatives: aggregate to month or to brand level to shrink the 185 MB CSV. Weekly UPC-store grain is the standard scanner-data grain, keeps the model honest (every number is re-derivable), and Power BI imports 4.6 M rows in under a minute from CSV. Measures do all aggregation.

## D6. Unit price = revenue-weighted price per 100 g
- `Price per 100g = Revenue / (ounces sold x 28.3495) x 100`, i.e. a volume-weighted average, not a simple average of shelf prices. This is what a pricing manager means by "realised" price per unit, and it is additive across any slice. Price per oz and average pack price are also provided.
- Brand Price Index = brand price per 100 g / category price per 100 g in the **same stores and weeks** x 100. `REMOVEFILTERS` is applied to Product and Brand only, so the index is a like-for-like comparison. (Consequence: filtering to one store tier makes the all-brand index 100 by construction; use `Price per 100g` to compare tiers in absolute terms, which is what visual 2b does.)

## D7. Store segment = Dominick's price tier (High / Medium / Low) from the Kilts demographics file
- `priclow / pricmed / prichigh` dummies map to Low (8 "Cub-fighter" stores near Cub Foods), Medium (56), High (22); 7 stores have no demographics row and are "Unknown". Pricing zone (1-16) and store cluster (A-D) are kept as extra attributes.

## D8. Elasticity model
- `ln(units_ist) = e ln(price_ist) + b promo_ist + a_is + g_t + u_ist`, estimated per brand by OLS after two-way demeaning (UPC x store fixed effects and week fixed effects), standard errors clustered by UPC x store. Reported: coefficient, SE, 95% CI, within-R2, n, number of UPCs and stores.
- Why fixed effects: cross-sectional price differences between UPCs/stores are confounded with quality and demographics; within-UPC-within-store weekly variation (temporary price cuts, Dominick's zone pricing experiments) is far cleaner. Week effects absorb seasonality and chain-wide shocks.
- Promo control: Dominick's promo flag is under-recorded (set only when a code was keyed). Including it separates the pure price effect from display/feature effects; dropping it makes the top five brands look 0.5-0.75 more elastic (robustness column `Elasticity (no promo control)`). The with-control estimate is used in the simulator; the gap is disclosed.
- Results: all 9 brands negative and inside the -0.3 to -5 plausibility window; major brands -1.65 (Private Label) to -2.51 (Nabisco); category -2.08 (CI -2.10 to -2.06). No flags, so no further endogeneity fixes were needed. "Other" (-0.77, R2 0.01) and Malt-O-Meal (n = 717) are statistically weak and shown as such in the Brand table.
- Known limitation (documented in README): this is a short-run elasticity driven mostly by temporary price cuts; it likely **overstates** the response to a permanent list-price increase. Treat simulator outputs as an upper bound on volume loss.

## D9. What-if simulator = constant-elasticity demand, brand by brand
- `Simulated Units = SUMX(VALUES(Brand[Brand]), Units x (1+p)^e)`, `Simulated Revenue = Revenue x (1+p)^(1+e)`. Each brand uses its own elasticity even when several brands are selected; the KPI card shows the revenue-weighted elasticity of the selection. A `Breakeven Volume Change %` measure (-p/(1+p)) is included so the user can compare the predicted loss with the loss that would leave revenue flat.
- Cross-price effects (switching to competitors) are **not** modelled; a brand-level own-price elasticity already nets some of it. Margin/profit is not modelled because retailer margin (`PROFIT`) is retailer-side, not manufacturer-side.

## D10. PBIP format choices (verified against the installed Power BI Desktop 2.159, Oct 2026)
- Semantic model in TMDL (`definition/` folder), report in PBIR (`definition/pages/...`). Microsoft Message Center MC1465770 (Sept 2026) made developer mode / PBIP GA and PBIR the default format, so **no Preview feature needs to be enabled** on Desktop builds from Sept 2026 on. On older builds (2.14x) enable *Power BI Project (.pbip) save option*, *Store semantic model using TMDL format* and *Store reports using enhanced metadata format (PBIR)* under File > Options > Preview features.
- Schema set pinned one matched version behind the newest published set for safety: `visualContainer/2.9.0` (May 2026), `page/2.1.0`, `report/3.3.0`, `pagesMetadata/1.1.0`, `versionMetadata/1.0.0`, `definitionProperties/2.0.0`, `pbipProperties/1.0.0`, `platformProperties/2.0.0`, `semanticModel/definitionProperties/1.0.0`. Desktop upgrades them silently on save. All 29 JSON files validate against the official schemas (`validate_pbip.py`, 0 errors).
- Base theme `CY24SU10` is shipped with the report in `StaticResources/SharedResources/BaseThemes/` (copied from the Desktop installation, as Desktop itself does).
- One Power Query parameter `DataFolder` (absolute path to `/output`) feeds all five CSV tables. The committed value is the placeholder `C:\path\to\output`; set it under Transform data > Manage parameters or rebuild with `--data-folder`.
- Visual/page names are 20-hex identifiers (Desktop style) derived deterministically from readable keys; folder names are readable (`m1_scatter`, ...). Lineage tags are uuid5 of object names so rebuilding does not churn them.

## D11. Bugs found by testing against the real engine, and fixes
- The what-if column was first written with `isNameInferred`; the engine then named it `Value` and `SELECTEDVALUE('Price Change %'[Price Change %])` failed to bind. Fixed by dropping `isNameInferred` (Desktop's own what-if tables do not set it).
- `Revenue` was first typed `Currency.Type` / `decimal`. Currency divided by double keeps 4 decimals, which truncated price per 100 g to two significant digits (0.64 instead of 0.6368). Fixed by typing revenue as double.
- `GENERATESERIES(-0.20, 0.20, 0.01)` produced 40 rows (floating-point step drops an endpoint). Replaced by an
  integer series -20..20 formatted `0"%"`, with the measure dividing by 100.
- All three were caught by connecting to the local Analysis Services instance Power BI Desktop starts for the open project, running a full refresh through XMLA, and comparing 20 DAX results to `output/metrics.json`.

## D11b. Layout revision (2026-11-14, second pass)
- Canvas changed from 1280 x 940 to 1600 x 690 so the whole page, including the what-if module, is visible on a
  laptop screen without scrolling in Desktop's "fit to width" view. The matrix got the full right half (852 px,
  fixed 118 px value columns) so all five pack tiers show; the module-2 line chart moved to yearly points and a
  visual-level filter (Kellogg's, General Mills, Post, Quaker, Private Label) to stay readable.

## D11c. Third pass (2026-11-15)
- What-if slicer opens pre-selected at +5 % (slicer `general.filter` default) so module 3 shows impact numbers
  immediately; the DAX default (no selection) stays 0 %. The single-value slider applied the default to the data
  but displayed the range minimum, so the slicer is a single-select dropdown instead. KPI cards 64 px tall / 18 pt callout and slicers 54 px
  tall so labels are not clipped.

## D11d. Company-neutral naming (2026-11-15)
- Project renamed from its working title to "Cereal Pricing" (`.pbip`, `.SemanticModel`, `.Report`, all internal references)
  and the GitHub repo to `cereal-pricing-dashboard`; dashboard subtitle says "Portfolio project (public academic data)".
  Product/brand names inside the data are untouched. Module-3 impact chart is a horizontal bar with brand labels and
  $M data labels; the matrix got 200 px so all nine brands plus Total show without scrolling.

## D12. Verification performed
- `prep.py` summary printed and saved to `output/data_quality_report.md`; referential integrity asserted in code.
- `validate_pbip.py`: every JSON file against its `$schema` (official repo), plus a TMDL lint (tabs, `///` placement, name clashes).
- Power BI Desktop 2.159 opened the `.pbip` with no errors, loaded all 7 partitions (37-43 s) and all 24 measures compiled; dashboard numbers match Python within rounding.

## D13. Not done / out of scope
- No Power BI Service publish, no RLS, no incremental refresh (static 1989-97 data).
- No mobile layout.
- Cross-price elasticities and a margin/profit layer are natural extensions.
