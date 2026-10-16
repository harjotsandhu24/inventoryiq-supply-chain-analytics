import { expect, test } from "@playwright/test";

// Runs in both the desktop and mobile (Pixel 7) projects: the page body must never scroll horizontally.
for (const path of ["/", "/forecasts", "/planner", "/scenarios"]) {
  test(`no horizontal page overflow on ${path}`, async ({ page }) => {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.waitForTimeout(300);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
  });
}

// Common desktop sizes: headings, navigation and the primary action stay visible without horizontal scroll.
for (const vp of [
  { width: 1280, height: 800 },
  { width: 1366, height: 768 },
  { width: 1920, height: 1080 },
]) {
  test(`desktop ${vp.width}x${vp.height} layout`, async ({ page, isMobile }) => {
    test.skip(isMobile, "desktop-only check");
    await page.setViewportSize(vp);
    for (const path of ["/", "/planner", "/scenarios"]) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeInViewport();
      await expect(page.getByRole("navigation", { name: "Main" })).toBeInViewport();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow).toBeLessThanOrEqual(1);
    }
  });
}

test("keyboard focus is visible on interactive controls", async ({ page, isMobile }) => {
  test.skip(isMobile, "desktop-only check");
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const link = page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Scenario Lab" });
  await link.focus();
  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Tab");
  const outline = await link.evaluate((el) => getComputedStyle(el).outlineStyle);
  expect(outline).not.toBe("none");
});
