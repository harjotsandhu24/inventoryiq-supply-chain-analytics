// InventoryIQ - planning inputs (MODELED forecast + SIMULATED supplier terms and stock)
let
    CsvFolder = "C:\Users\<you>\inventoryiq-supply-chain-analytics\deliverables\m5\csv",
    Source = Csv.Document(File.Contents(CsvFolder & "\planning_inputs.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"series", type text}, {"item_id", type text}, {"store_id", type text}, {"cat_id", type text},
        {"supplier_id", type text}, {"method", type text}, {"pattern", type text}, {"abc", type text}, {"xyz", type text},
        {"mu", type number}, {"sigma", type number}, {"lead_time_mean", type number}, {"lead_time_sd", type number},
        {"case_pack", Int64.Type}, {"moq_units", Int64.Type}, {"unit_price", Currency.Type}, {"unit_cost", Currency.Type},
        {"on_hand", type number}, {"on_order", type number}, {"holdout_wape_selected", type number},
        {"holdout_wape_naive", type number}
    }, "en-US")
in
    Typed
