# Kill-trigger vocabulary (spec §8.4)

Up to five, chosen from this menu only. Python bounds each threshold into its range
(`config/value.yaml → rules.claude.kill_bounds`) and evaluates every one each night; a trigger
within 10% of firing opens a Minor re-evaluation (§7.1 trigger 6), a fired one raises a review
card. None of them sells anything on its own.

| Kind | Fires when | Threshold (range) |
|---|---|---|
| `revenue_growth_below` | the newest fiscal year's revenue growth is below x% | -30 to 10 |
| `fcf_ttm_negative` | TTM free cash flow is below zero | none |
| `net_debt_to_ebitda_above` | net debt / EBITDA is above y | 1 to 6 |
| `dilution_above` | the diluted share count grows more than z% a year | 1 to 10 |
| `gross_margin_below` | the newest fiscal year's gross margin is below m% | 0 to 90 |
| `guidance_cut` | a grounded filing fact says guidance was cut | none |
| `customer_loss` | a grounded filing fact says a material customer was lost | none |

`insider_selling_cluster` (in the spec's menu) is not built: there is no Form 4 feed yet.
