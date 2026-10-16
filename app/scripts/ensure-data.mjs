// Ensures the app has analytical data to load.
// If public/data is missing (fresh clone), copies the committed SYNTHETIC demo fixture.
// Run `npm run data:demo` to force the synthetic fixture even when M5-derived data exists.
import { cpSync, existsSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const target = join(root, "public", "data");
const fixture = join(root, "fixtures", "demo-data");
const force = process.argv.includes("--force-demo");

if (force || !existsSync(join(target, "manifest.json"))) {
  if (!existsSync(fixture)) {
    console.error("No app data found and no demo fixture available. Run the Python pipeline first.");
    process.exit(1);
  }
  if (existsSync(target)) rmSync(target, { recursive: true, force: true });
  cpSync(fixture, target, { recursive: true });
  console.log("InventoryIQ: using SYNTHETIC demo data (fixtures/demo-data).");
} else {
  console.log("InventoryIQ: using existing data in public/data.");
}
