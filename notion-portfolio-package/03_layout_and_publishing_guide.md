# Notion portfolio: layout and publishing guide

A step-by-step guide for a first Notion portfolio. Everything here works on Notion's **free** plan: no paid themes, custom domain or other hosting. Nothing in this package has been published yet.

**What is ready:** the text (`01_homepage.md`, `02_inventoryiq_case_study.md`) and four genuine screenshots (`screenshots/`) of the running app on synthetic demonstration data.

**What you still supply:** the links marked `{{...}}` (section 5).

Notion does not import Markdown layouts exactly. Paste the text, then arrange images and columns by hand as described below. This takes about 20 minutes.

## 1. Create the homepage

1. Sign in at notion.so (a free account is fine). In the sidebar, click **+ Add a page**.
2. Type the title: **Supply Chain Analytics Portfolio**.
3. Click **Add cover**, then **Change cover > Color** and choose a plain dark blue. Skip the icon or use a simple one (no emoji).
4. Under the title, type the subtitle as normal text: *Independent projects focused on inventory planning, purchasing decisions, and operational performance.*
5. Type `/divider` and press Enter.
6. Add a **Heading 2**: `InventoryIQ — Inventory Forecasting & Replenishment`. Below it, add the one-sentence description from `01_homepage.md`.
7. Drag `screenshots/03-planner.png` from this folder into the page, under the description. Resize it to full width.
8. Below the image, add the links line. GitHub becomes a link once your repository exists; until then, leave it out.
9. Add a divider and the single line *More projects are in progress and will be added when complete.* Do not list unfinished projects as if they were done.

**Width:** open the **...** menu (top right), turn on **Full width** for the homepage, and leave **Small text** off.

## 2. Create the InventoryIQ case-study page

1. On the homepage, put the cursor under the InventoryIQ screenshot, type `/page` and name the new page **InventoryIQ — Inventory Forecasting & Replenishment**. It is now a sub-page with a link on the homepage.
2. Open it and paste the text of `02_inventoryiq_case_study.md`. Notion turns `##` lines into headings and `-` lines into bullets. Keep the sections in exactly this order: Why I built this, Tools I used, What I did, Visual proof, What I learned, What I'd do next, Links.
3. Delete the Markdown image lines (`![...](...)`). Images are added by dragging files in instead.
4. **Visual proof layout:**
   1. Drag `01-overview.png` and `02-forecast.png` into the page side by side. Notion makes two columns when you drop the second image beside the first.
   2. Do the same with `03-planner.png` and `04-scenario.png` underneath.
   3. Click each image, choose **Caption**, and paste the short italic caption from the text.
5. Optional cover for the case study: `03-planner.png` (**Add cover > Upload**).
6. Leave the case study at **standard width** so the text stays easy to read.

## 3. Style rules (corporate and minimal)

| Element | Setting |
|---|---|
| Colors | Notion's **Blue** text for links only. Optionally one **Gray background** callout. No other colors. |
| Headings | Heading 1 = page title (automatic); Heading 2 = sections |
| Text | Short paragraphs, at most four bullets per list |
| Images | Only the four provided screenshots. No stock photos or AI images. |
| Emoji and badges | None |

## 4. Add the demo video (after you upload it)

The silent walkthrough is `demo-video/inventoryiq_demo_synthetic.webm` (synthetic data).

1. Upload it yourself to YouTube (set **Unlisted** if you prefer), Loom or Google Drive (set "anyone with the link").
2. In the case study, under **Links**, type `/video` and paste the video URL, or simply link the text **Watch Demonstration**.
3. Use `demo-video/thumbnail.png` as the YouTube thumbnail if asked.

## 5. Replace the placeholders

| Placeholder | Replace with | Available when |
|---|---|---|
| `{{GITHUB_URL}}` | `https://github.com/<your-account>/inventoryiq-supply-chain-analytics` | After you approve and push the repository |
| `{{VIDEO_URL}}` | Your hosted video link | After you upload the video |
| `{{EXCEL_URL}}` | The GitHub file link to `deliverables/synthetic/InventoryIQ_Analysis.xlsx` (synthetic demo workbook) | After the repository is public |
| `{{EMAIL_OR_LINKEDIN}}` | Your preferred contact | Now |

Never publish a page that still shows `{{...}}`. Remove any link whose destination does not exist yet.

## 6. Publish

1. On the homepage, click **Share** (top right), open the **Publish** tab and click **Publish**.
2. Sub-pages are published with their parent. Check the case study by opening its link while signed out.
3. Optional: turn on **Search engine indexing**.
4. Copy the public `notion.site` link for your résumé and LinkedIn.

## 7. Final checks (2 minutes)

- Open the public link in a private browser window. All four images should load, and the case-study link should work.
- No `{{...}}` placeholders remain.
- Every screenshot caption says, or sits under a line saying, that it shows synthetic demonstration data.
- **20-second test:** ask someone to look for 20 seconds, then tell you what InventoryIQ does, one finding, and where the code is.
