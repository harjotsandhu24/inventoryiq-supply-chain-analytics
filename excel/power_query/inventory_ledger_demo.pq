// InventoryIQ - daily simulated inventory ledger with calendar dates
// Day 1 is 2011-01-29 for the M5 data and 2021-01-02 for the synthetic demo data: set StartDate to match.
let
    StartDate = #date(2011, 1, 29),
    CsvFolder = "C:\Users\<you>\inventoryiq-supply-chain-analytics\deliverables\m5\csv",
    Source = Csv.Document(File.Contents(CsvFolder & "\inventory_ledger_demo.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"scope", type text}, {"policy", type text}, {"series", type text}, {"day", Int64.Type},
        {"opening", Int64.Type}, {"receipts", Int64.Type}, {"demand", Int64.Type}, {"fulfilled", Int64.Type},
        {"lost", Int64.Type}, {"closing", Int64.Type}, {"on_order", Int64.Type}, {"ordered", Int64.Type}
    }, "en-US"),
    WithDate = Table.AddColumn(Typed, "date", each Date.AddDays(StartDate, [day] - 1), type date),
    BalanceCheck = Table.AddColumn(WithDate, "balance_ok", each [opening] + [receipts] - [fulfilled] = [closing], type logical)
in
    BalanceCheck
