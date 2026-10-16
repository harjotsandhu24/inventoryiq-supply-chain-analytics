-- Business question: Which (SIMULATED) suppliers create the greatest delivery risk?
-- Approach: compare realised and promised lead times of simulated purchase orders, measure late
--           share and variability, and attach the sales value exposed to each supplier.
--           All suppliers and orders are simulated assumptions, not Walmart vendors.
-- Skills: multi-CTE joins, conditional aggregation, statistical aggregates, ranking.
-- Tables: purchase_orders, suppliers, supplier_assumptions, replenishment_recommendations

WITH po AS (
    SELECT
        supplier_id,
        lead_time_realised,
        arrival_day - expected_arrival_day AS days_late
    FROM purchase_orders
    WHERE scope = 'model_stores'
),
delivery AS (
    SELECT
        supplier_id,
        COUNT(*) AS purchase_orders,
        ROUND(AVG(lead_time_realised), 2) AS avg_lead_time,
        ROUND(STDDEV_SAMP(lead_time_realised), 2) AS sd_lead_time,
        MAX(lead_time_realised) AS max_lead_time,
        ROUND(AVG(CASE WHEN days_late > 0 THEN 1.0 ELSE 0.0 END), 3) AS late_share,
        ROUND(AVG(GREATEST(days_late, 0)), 2) AS avg_days_late
    FROM po
    GROUP BY supplier_id
),
exposure AS (
    SELECT
        a.supplier_id,
        COUNT(*) AS demo_lines,
        SUM(CASE WHEN r.risk = 'High' THEN 1 ELSE 0 END) AS high_risk_lines,
        ROUND(SUM(r.mu * a.unit_price) * 28, 2) AS forecast_28d_sales_value
    FROM replenishment_recommendations r
    JOIN supplier_assumptions a USING (series_id)
    GROUP BY a.supplier_id
)
SELECT
    s.supplier_id,
    s.supplier_name,
    s.lead_time_mean_days AS promised_lead_time,
    d.*  EXCLUDE (supplier_id),
    e.demo_lines,
    e.high_risk_lines,
    e.forecast_28d_sales_value,
    RANK() OVER (ORDER BY d.late_share * d.avg_lead_time DESC) AS delivery_risk_rank
FROM suppliers s
LEFT JOIN delivery d USING (supplier_id)
LEFT JOIN exposure e USING (supplier_id)
ORDER BY delivery_risk_rank;
