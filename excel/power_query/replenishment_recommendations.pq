// InventoryIQ - replenishment recommendations (Balanced settings)
let
    CsvFolder = "C:\Users\<you>\inventoryiq-supply-chain-analytics\deliverables\m5\csv",
    Source = Csv.Document(File.Contents(CsvFolder & "\replenishment_recommendations.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"series", type text}, {"item_id", type text}, {"store_id", type text}, {"dept_id", type text},
        {"cat_id", type text}, {"supplier_id", type text}, {"risk", type text}, {"status", type text},
        {"mu", type number}, {"sigma", type number}, {"lead_time", type number}, {"protection_period", type number},
        {"safety_stock", type number}, {"reorder_point", type number}, {"order_up_to", type number},
        {"on_hand", Int64.Type}, {"on_order", Int64.Type}, {"inventory_position", type number},
        {"recommended_qty", Int64.Type}, {"final_qty", Int64.Type}, {"unit_cost", Currency.Type},
        {"order_value", Currency.Type}, {"priority_rank", Int64.Type}, {"p_stockout_lead_time", Percentage.Type},
        {"coverage_days", type number}, {"expected_receipt_date", type date}, {"reason", type text}
    }, "en-US"),
    Sorted = Table.Sort(Typed, {{"priority_rank", Order.Ascending}})
in
    Sorted
