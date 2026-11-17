# Three insights for a pricing manager

All numbers are computed by `prep.py` from the cleaned Dominick's cereal data (Sept 1989 - May 1997, 93 stores,
441 UPCs, $256.1 M revenue) and stored in `output/metrics.json`. They are reproduced live by the dashboard measures.

---

## 1. Pack architecture: the quantity discount is 40 %, and brands use it very differently

**Number.** Volume-weighted price per 100 g by pack-size tier:

| Pack tier | $/100 g | vs small |
|---|---:|---:|
| Small (< 12 oz) | 0.796 | - |
| Medium (12-16 oz) | 0.704 | -12 % |
| Large (16-20 oz) | 0.596 | -25 % |
| Family (20-30 oz) | 0.555 | -30 % |
| Club (30 oz +) | 0.475 | -40 % |

Within that curve the two leaders sit on different ladders: Kellogg's drops from $0.785 (small) to $0.524 (family),
a 33 % discount, while General Mills only drops from $0.840 to $0.678 (19 %). In family packs General Mills
therefore realises **29 % more per 100 g than Kellogg's**, yet it holds 31.5 % revenue share against Kellogg's 37.0 %.

**So what.** The price-pack architecture, not the headline shelf price, is where most of the per-unit price
difference between brands lives. A manager reviewing a price increase should first check where each pack sits on
the curve: a brand whose large packs are already 30 % cheaper per 100 g than its small packs is effectively
subsidising heavy buyers, and a pack-size change (fewer grams at the same shelf price) moves per-100 g price with
far less visible shelf-price shock than a list-price increase. The matrix in module 1 shows exactly which cells
(brand x tier) are out of line with the category curve.

---

## 2. Price monitoring: private label's discount narrowed by ~20 index points when brands cut prices

**Number.** Brand price index vs the category average (= 100, same stores and weeks):

| Brand | Whole period | 1991 | 1995 | 1996 |
|---|---:|---:|---:|---:|
| General Mills | 114.5 | 115.2 | 107.4 | 114.4 |
| Ralston | 114.9 | 107.8 | 122.6 | 116.6 |
| Kellogg's | 96.6 | 97.8 | 102.5 | 97.6 |
| Post | 98.3 | 97.6 | 97.1 | 94.9 |
| Quaker | 87.4 | 90.4 | 86.4 | 83.7 |
| Private Label | 67.5 | 59.2 | 69.6 | 80.2 |

Private label sold at a 41 % discount to the category in 1991 but only a 20 % discount in 1996; in the same
year Kellogg's index fell 5 points (102.5 to 97.6) and Post's fell to 94.9 - the branded list-price cuts of
1995-96 show up directly in the index. Across store tiers the whole category is priced 101.8 (High-tier stores)
vs 97.3 (Low / "Cub-fighter" stores), a 4.6 % zone spread.

**So what.** A brand price index per quarter and per store tier is the early-warning system for competitor
moves: it is scale-free (works across pack sizes), it isolates relative position from inflation, and it shows
whether a competitor's cut was chain-wide or confined to a price zone. In this data the private-label gap
narrowed by 21 index points over five years while the three largest brands' indices moved by 3 points or less, which
is the kind of shift a manager has to decide on: follow the cut, defend with promotions, or hold price and accept
share loss.

---

## 3. Price-increase what-if: at a promo-driven elasticity of about -2, the outcome of a price increase depends on how it is executed, not on whether to raise prices

**Number.** Own-price elasticity (log-log, UPC x store and week fixed effects, promo control):
Kellogg's -2.17 (95 % CI -2.21 to -2.14, n = 1.46 M store-UPC-weeks), category -2.08. Applying Kellogg's
elasticity to its $94.8 M baseline:

| Scenario | Volume | Revenue | Revenue $ |
|---|---:|---:|---:|
| +5 % price | -10.1 % | -5.6 % | -$5.28 M |
| +10 % price | -18.7 % | -10.6 % | -$10.04 M |

Break-even volume loss at +5 % is -4.8 % (revenue is flat if volume falls by less than that). The simulator's
-10.1 % is twice the break-even figure - but it is the wrong number to take at face value. The elasticity is
estimated from short-run, temporary price cuts (the only price variation in scanner data), and shoppers react to
a two-week deal with stockpiling and brand switching that a permanent list-price change does not trigger. The
estimate therefore **overstates** the reaction to an annual list-price increase: the true outcome lies between
the -4.8 % break-even and the -10.1 % estimate.

**So what.** For a manufacturer that takes an annual price increase, the question is not whether but how. Three
execution levers that this dashboard helps size:

1. **Price-pack architecture (insight 1).** Taking part of the increase through pack size moves price per 100 g
   with far less shelf-price visibility than a list-price step; the brand x tier matrix shows which cells have
   headroom against the category curve (e.g. Kellogg's family packs at $0.52 vs General Mills at $0.68).
2. **Cost pass-through with a margin case.** The simulator gives the revenue-side bound; paired with input-cost
   inflation it shows how much of the increase is margin protection rather than margin expansion, which is the
   argument retailers accept.
3. **Price-promo balance.** The gap between -4.8 % and -10.1 % is largely promotional reaction, so the depth and
   frequency of the promo calendar after the increase decide where in that range the brand lands.

The dashboard keeps each brand's own elasticity, so a portfolio-wide increase is simulated brand by brand rather
than with one category average.
