# Simulated assumptions (version `2026.10-v1`)

The M5 dataset contains sales, prices and a calendar. Everything else an inventory planner needs is **assumed** here. The values are deterministic: no assumption is fitted to the simulation or holdout periods, and rules based on sales use only data from before the simulation start. They are defined in `src/inventoryiq/config.py` and `src/inventoryiq/suppliers.py`. **None of these values describe Walmart's actual suppliers, costs or operations.**

## Suppliers (fictional, assigned by department)

| Supplier | Departments | Mean lead time | Lead-time sd | MOQ | Order cost / PO line | Capacity factor | On-time rate (informational) |
|---|---|---:|---:|---:|---:|---:|---:|
| SUP-01 Dry Grocery Supplier | FOODS_1 | 5 d | 1.0 d | 1 case | $6 | 1.6x | 93% |
| SUP-02 Packaged Foods Supplier | FOODS_2 | 6 d | 1.5 d | 1 case | $6 | 1.6x | 90% |
| SUP-03 Regional Fresh & Staples DC | FOODS_3 | 3 d | 0.8 d | 1 case | $4 | 1.5x | 95% |
| SUP-04 Import Hobby Goods Supplier | HOBBIES_1, HOBBIES_2 | 14 d | 4.0 d | 2 cases | $9 | 1.8x | 74% |
| SUP-05 Household Essentials Supplier | HOUSEHOLD_1 | 7 d | 2.0 d | 1 case | $7 | 1.6x | 88% |
| SUP-06 Home Goods Supplier | HOUSEHOLD_2 | 10 d | 3.5 d | 1 case | $8 | 1.6x | 81% |

- **Realised lead times** are drawn from a gamma distribution with the stated mean and sd, rounded to whole days with a minimum of 1. Draws use common random numbers per supplier and order day, seeded with `RANDOM_SEED = 20260101` for the main window and a window-specific seed for the confirmation window.
- **Capacity** in units per 7-day review = capacity factor x average daily volume of the supplier's lines in scope (364 days before the window) x 7.

## Item terms

| Assumption | Rule |
|---|---|
| Case pack | Set per item from its mean listed-day velocity across stores: >=5 units/day -> 12; >=2 -> 6; >=0.75 -> 4; >=0.25 -> 2; otherwise 1 |
| MOQ | Supplier minimum cases x case pack |
| List price | **Observed:** median weekly shelf price over the 364 days before the simulation start |
| Unit cost | List price x (1 - category gross margin) |
| Gross margin | Foods 30%, Household 38%, Hobbies 42% |

## Costs

| Assumption | Value |
|---|---|
| Annual holding cost | 25% of unit cost per unit-year, charged on closing on-hand stock (not on stock in transit) |
| Ordering cost | Per purchase-order line, by supplier (see table above) |
| Shortage penalty | 1.5 x unit gross margin per lost unit (lost margin plus goodwill) |
| Purchasing spend | Reported, but **not** counted as a cost |

## Inventory starting state

- **Simulation start:** both policies begin with ceil(28-day average sales x (lead time + 14 days)) units, rounded to cases, and nothing on order.
- **Planning snapshot (app):** stock on hand and in-transit purchase orders are the end state of the **basic policy** simulation on the last observed day (2016-05-22). This represents a business running the status-quo rule that is now asking what the forecast-informed planner recommends.

## Planning defaults (Balanced)

| Setting | Value |
|---|---|
| Target cycle service level | 95% |
| Review interval | 7 days |
| Maximum days of supply per order | 28 (policy v2) |
| Budget | none (capacity still applies) |
| Intermittent fallback | on (for intermittent or lumpy items) |

## Presets

| Preset | Settings |
|---|---|
| Protect Availability | 99% cycle service level |
| Limit Spending | Budget = 60% of the Balanced plan's spend, computed at runtime |
