-- Business question: Where does the forecast-informed policy help or hurt versus the basic rule?
-- Approach: aggregate the SIMULATED inventory ledger by policy and category; fill rate and average
--           stock come straight from the ledger, so the totals reconcile with simulation_summary.
-- Skills: joins, conditional aggregation, pivot with FILTER, CTEs.
-- Tables: inventory_ledger, series, products, supplier_assumptions

WITH by_cat AS (
    SELECT
        p.cat_id,
        l.policy,
        SUM(l.demand) AS demand,
        SUM(l.fulfilled) AS fulfilled,
        SUM(l.lost) AS lost,
        AVG(l.closing * a.unit_cost) * COUNT(DISTINCT l.series_id) AS avg_inventory_value
    FROM inventory_ledger l
    JOIN series s USING (series_id)
    JOIN products p ON p.item_id = s.item_id
    JOIN supplier_assumptions a USING (series_id)
    WHERE l.scope = 'model_stores'
    GROUP BY p.cat_id, l.policy
)
SELECT
    cat_id,
    ROUND(MAX(fulfilled / demand) FILTER (WHERE policy = 'basic'), 4) AS fill_rate_basic,
    ROUND(MAX(fulfilled / demand) FILTER (WHERE policy = 'forecast'), 4) AS fill_rate_forecast,
    MAX(lost) FILTER (WHERE policy = 'basic') AS lost_units_basic,
    MAX(lost) FILTER (WHERE policy = 'forecast') AS lost_units_forecast,
    ROUND(MAX(avg_inventory_value) FILTER (WHERE policy = 'basic'), 0) AS avg_inventory_value_basic,
    ROUND(MAX(avg_inventory_value) FILTER (WHERE policy = 'forecast'), 0) AS avg_inventory_value_forecast,
    CASE
        WHEN MAX(lost) FILTER (WHERE policy = 'forecast') < MAX(lost) FILTER (WHERE policy = 'basic')
         AND MAX(avg_inventory_value) FILTER (WHERE policy = 'forecast') <= MAX(avg_inventory_value) FILTER (WHERE policy = 'basic')
            THEN 'forecast policy better on both'
        WHEN MAX(lost) FILTER (WHERE policy = 'forecast') < MAX(lost) FILTER (WHERE policy = 'basic')
            THEN 'fewer lost sales, more inventory'
        WHEN MAX(avg_inventory_value) FILTER (WHERE policy = 'forecast') < MAX(avg_inventory_value) FILTER (WHERE policy = 'basic')
            THEN 'less inventory, more lost sales'
        ELSE 'basic policy better on both'
    END AS tradeoff
FROM by_cat
GROUP BY cat_id
ORDER BY cat_id;
