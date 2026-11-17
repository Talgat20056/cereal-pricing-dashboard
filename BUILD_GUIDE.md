# BUILD_GUIDE - rebuilding the report page by hand (fallback)

The generated PBIR report in `pbip/Cereal Pricing.Report` opens as is in Power BI Desktop (Sept 2026+). Use this
guide only if your Desktop build cannot read the report folder: open the semantic model alone (delete the
`Cereal Pricing.Report` folder and open `Cereal Pricing.pbip`, or create a new report connected to the model) and
recreate the single page below. Field names are exactly as in the model. Positions are (x, y / width x height).

Page: **Pricing Dashboard**, canvas 1600 x 740 (Format page > Canvas settings > Custom), background #F3F4F6.

## Header
| Visual | Fields | Settings |
|---|---|---|
| Text box (16,6 / 900x50) | "Ready-to-Eat Cereal: Price Architecture, Price Monitoring & Price-Increase Simulator" 14 pt bold; second line 9 pt grey: "Dominick's Finer Foods (Chicago), 93 stores, 441 UPCs, Sep 1989 - May 1997 \| Source: Kilts Center, Chicago Booth \| Portfolio project (public academic data)" | no background/border |
| Slicer (940,6 / 200x54) | `Product[Brand]` | style Dropdown, header "Brand" |
| Slicer (1160,6 / 200x54) | `Store[Price Tier]` | Dropdown, header "Store price tier" |
| Slicer (1380,6 / 204x54) | `Calendar[Year]` | Dropdown, header "Year" |

## KPI row (y = 66, height 64, width 388 at x = 16 / 420 / 824, width 356 at x = 1228)
Card visuals: `[Revenue]`, `[Units]` (rename "Packages sold"), `[Price per 100g]` ("Avg price per 100 g"),
`[Promo Share of Units]` ("Promo share of units"). Callout 18 pt, category label 9 pt, title off.

## Module 1 - Price architecture (y = 138, height 200)
| Visual | Wells | Format |
|---|---|---|
| Scatter chart (16,138 / 700x200) | Values: `Product[Product]`; Legend: `Product[Brand]`; X: `[Avg Pack Size (oz)]`; Y: `[Price per 100g]`; Size: `[Revenue]` | Title "1 \| Price architecture: price per 100 g vs pack size (bubble = revenue, one bubble per UPC)"; legend right, 8 pt; axis titles on; Y starts at 0; marker transparency 25 % |
| Matrix (732,138 / 852x200) | Rows: `Product[Brand]`; Columns: `Product[Pack Tier]`; Values: `[Price per 100g]` | Title "1 \| Price per 100 g by brand x pack-size tier (blank = not sold)"; font 8; row & column subtotals on; auto-size column width off, value column width 118; sort rows by Price per 100g desc |

## Module 2 - Price monitoring (y = 346, height 154)
| Visual | Wells | Format |
|---|---|---|
| Line chart (16,346 / 700x154) | X: `Calendar[Year]`; Legend: `Product[Brand]`; Y: `[Brand Price Index]`; **visual-level filter** `Product[Brand]` = Kellogg's, General Mills, Post, Quaker, Private Label | Title "2 \| Brand price index vs category average (= 100) by year - top 4 brands and private label"; legend top; line width 2; Analytics > Y-axis constant line = 100, dashed grey, data label on |
| Clustered column chart (732,346 / 852x154) | X-axis: `Product[Brand]`; Legend: `Store[Price Tier]`; Y-axis: `[Price per 100g]` | Title "2 \| Price per 100 g by brand and store price tier (High / Medium / Low zone)"; legend top titled "Store tier"; sort by Price per 100g desc |

## Module 3 - Price-increase what-if (y = 508, height 222)
| Visual | Wells | Format |
|---|---|---|
| Slicer (16,508 / 230x78) | `'Price Change %'[Price Change %]` | Slicer settings > style **Dropdown**, Selection > **Single select** on; pick 5 as the saved default; header "3 \| Price change % (what-if)" |
| Card (16,594 / 230x136) | `[Elasticity (selected)]` | label "Own-price elasticity (selection)" |
| Card (262,508 / 170x66) | `[Volume Impact %]` | label "Volume impact" |
| Card (444,508 / 170x66) | `[Revenue Impact %]` | label "Revenue impact" |
| Card (626,508 / 170x66) | `[Revenue Impact $]` | label "Revenue impact ($, period)" |
| Card (812,508 / 170x66) | `[Breakeven Volume Change %]` | label "Break-even volume change" |
| Clustered column chart (262,582 / 888x148) | X-axis: `Product[Brand]`; Y-axis: `[Revenue Impact $]`; Tooltips: `[Revenue]` | Title "3 \| Revenue impact ($M) by brand at the selected price change"; data labels on, 8 pt, display units Millions, 1 decimal; Y axis hidden; sort by Revenue Impact $ ascending; legend off |
| Table (1164,508 / 420x222) | `Brand[Brand]`, `Brand[Elasticity]` ("e"), `Brand[CI Low (95%)]` ("CI low"), `Brand[CI High (95%)]` ("CI high"), `Brand[R2 Within]` ("R2"), `Brand[N Obs]` ("n") | Title "3 \| Elasticity by brand (log-log, UPC x store + week fixed effects)"; font 8; totals off; sort by `Brand[Revenue Share]` desc (add it, then hide the column) |

## Checks after building
- Cards with no slicer selection: Revenue $256.1 M, Packages 88.0 M, Price per 100 g $0.637, Promo share 22.4 %.
- Set the what-if slicer to 5 and the Brand slicer to Kellogg's: Volume impact -10.1 %, Revenue impact -5.6 %,
  Revenue impact $ about -$5.28 M, elasticity -2.17.
- Store price tier = High: all-brand index shows 100.0 (by design - like-for-like within the selected stores).
