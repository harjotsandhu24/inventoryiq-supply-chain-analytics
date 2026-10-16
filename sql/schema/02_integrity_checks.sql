-- Integrity checks. Every row returns a check name and a violation count; all counts must be 0.
-- Executed by the pipeline (src/inventoryiq/database.py) and by tests/test_database.py.

SELECT 'daily_sales duplicate (series_id, day)' AS check_name, COUNT(*) AS violations
FROM (SELECT series_id, day FROM daily_sales GROUP BY 1, 2 HAVING COUNT(*) > 1)
UNION ALL
SELECT 'daily_sales negative units', COUNT(*) FROM daily_sales WHERE units < 0
UNION ALL
SELECT 'daily_sales unknown series', COUNT(*)
FROM daily_sales d LEFT JOIN series s USING (series_id) WHERE s.series_id IS NULL
UNION ALL
SELECT 'daily_sales day missing from calendar', COUNT(*)
FROM daily_sales d LEFT JOIN calendar c USING (day) WHERE c.day IS NULL
UNION ALL
SELECT 'daily_sales units sold while item unlisted', COUNT(*)
FROM daily_sales d
JOIN series s USING (series_id)
JOIN calendar c USING (day)
LEFT JOIN prices p ON p.item_id = s.item_id AND p.store_id = s.store_id AND p.wm_yr_wk = c.wm_yr_wk
WHERE p.sell_price IS NULL AND d.units > 0
UNION ALL
SELECT 'daily_sales rows per series not equal to observed days', COUNT(*)
FROM (SELECT series_id, COUNT(*) AS n FROM daily_sales GROUP BY 1)
WHERE n <> (SELECT MAX(day) FROM daily_sales)
UNION ALL
SELECT 'prices non-positive', COUNT(*) FROM prices WHERE sell_price <= 0
UNION ALL
SELECT 'prices week missing from calendar', COUNT(*)
FROM prices p WHERE NOT EXISTS (SELECT 1 FROM calendar c WHERE c.wm_yr_wk = p.wm_yr_wk)
UNION ALL
SELECT 'series item-store pair without prices', COUNT(*)
FROM series s WHERE NOT EXISTS (SELECT 1 FROM prices p WHERE p.item_id = s.item_id AND p.store_id = s.store_id)
UNION ALL
SELECT 'series id not item_store composition', COUNT(*)
FROM series WHERE series_id <> item_id || '_' || store_id
UNION ALL
SELECT 'price join fan-out (rows per series-day > 1)', COUNT(*)
FROM (
    SELECT s.series_id, c.day, COUNT(*) AS n
    FROM series s
    JOIN calendar c ON c.day BETWEEN 1 AND 28
    LEFT JOIN prices p ON p.item_id = s.item_id AND p.store_id = s.store_id AND p.wm_yr_wk = c.wm_yr_wk
    GROUP BY 1, 2
) WHERE n > 1
UNION ALL
SELECT 'ledger balance (opening + receipts - fulfilled <> closing)', COUNT(*)
FROM inventory_ledger WHERE opening + receipts - fulfilled <> closing
UNION ALL
SELECT 'ledger demand split (fulfilled + lost <> demand)', COUNT(*)
FROM inventory_ledger WHERE fulfilled + lost <> demand
UNION ALL
SELECT 'ledger continuity (opening <> previous closing)', COUNT(*)
FROM (
    SELECT opening, LAG(closing) OVER (PARTITION BY scope, policy, series_id ORDER BY day) AS prev_closing
    FROM inventory_ledger
) WHERE prev_closing IS NOT NULL AND opening <> prev_closing
UNION ALL
SELECT 'ledger receipts not matching purchase orders', COUNT(*)
FROM (
    SELECT l.scope, l.policy, l.series_id, l.day, l.receipts, COALESCE(SUM(po.quantity), 0) AS po_qty
    FROM inventory_ledger l
    LEFT JOIN purchase_orders po
      ON po.scope = l.scope AND po.policy = l.policy AND po.series_id = l.series_id AND po.arrival_day = l.day
    GROUP BY ALL
) WHERE receipts <> po_qty
UNION ALL
SELECT 'purchase orders below MOQ or not whole cases', COUNT(*)
FROM purchase_orders po JOIN supplier_assumptions a USING (series_id)
WHERE po.quantity < a.moq_units OR po.quantity % a.case_pack <> 0
UNION ALL
SELECT 'recommendations below MOQ or not whole cases', COUNT(*)
FROM replenishment_recommendations r JOIN supplier_assumptions a USING (series_id)
WHERE r.final_qty > 0 AND (r.final_qty < a.moq_units OR r.final_qty % a.case_pack <> 0)
UNION ALL
SELECT 'recommendation funded above recommended quantity', COUNT(*)
FROM replenishment_recommendations WHERE final_qty > recommended_qty
UNION ALL
SELECT 'forecast evaluation missing actuals', COUNT(*)
FROM forecast_evaluation WHERE n_days <= 0;
