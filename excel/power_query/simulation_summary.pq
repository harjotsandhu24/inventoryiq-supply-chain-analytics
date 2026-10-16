// InventoryIQ - historical policy simulation summary (SIMULATED)
let
    CsvFolder = "C:\Users\<you>\inventoryiq-supply-chain-analytics\deliverables\m5\csv",
    Source = Csv.Document(File.Contents(CsvFolder & "\simulation_summary.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"policy", type text}, {"policy_label", type text}, {"scope", type text}, {"window", type text},
        {"lines", Int64.Type}, {"fill_rate", Percentage.Type}, {"cycle_service_level", Percentage.Type},
        {"lost_units", type number}, {"avg_inventory_value", Currency.Type}, {"purchase_orders", Int64.Type},
        {"purchasing_spend", Currency.Type}, {"holding_cost", Currency.Type}, {"ordering_cost", Currency.Type},
        {"shortage_penalty", Currency.Type}, {"modeled_total_cost", Currency.Type}
    }, "en-US")
in
    Typed
