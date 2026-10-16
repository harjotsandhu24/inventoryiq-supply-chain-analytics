import type { Metadata } from "next";
import "./globals.css";
import { AppShell } from "@/components/AppShell";
import { DataProvider } from "@/lib/data";

export const metadata: Metadata = {
  title: "InventoryIQ — Inventory Forecasting & Replenishment",
  description: "Demand forecasts, inventory risk, and purchase recommendations with supplier constraints.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <DataProvider>
          <AppShell>{children}</AppShell>
        </DataProvider>
      </body>
    </html>
  );
}
