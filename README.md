# Quest For Signs Of Life

A Python-generated static photography portfolio built from Google Maps Local Guide contributions — public art, travel landmarks, signs, and interesting places worth exploring.

---

## ⚡ The Primary Workflow: `sync`

**One command. That's it.**

After running the harvester bookmarklet, drop the downloaded file in your project folder and run:

```bash
python3 manage.py sync ~/Downloads/maps_contributions.json
```

`sync` does everything in a single pass:

1. **Imports** new photos from your harvested Google Maps contributions
2. **Updates** existing entries without creating duplicates
3. **Downloads** any remote CDN images to local disk
4. **Rebuilds** `index.html` — your portfolio is ready

> **No file? No problem.** Run `python3 manage.py sync` with no arguments and it will attempt to harvest directly from your Google Maps profile URL automatically.

---

## 🗺️ Step 0: Harvest Your Google Maps Photos

Before syncing, you need a `maps_contributions.json` file from your Google Maps profile:

1. Open [`tools/harvest_google_maps.html`](tools/harvest_google_maps.html) in your browser
2. Drag the **📸 Harvest Maps Photos** button to your bookmarks bar
3. Go to your [Google Maps Profile Photos](https://www.google.com/maps/contrib/109844961042142282833/photos)
4. Click the bookmarklet — it scrolls the page, collects all photo URLs with titles and locations, and auto-downloads `maps_contributions.json`
5. Run `sync` (see above)

Existing entries are matched by the stable Google photo ID and updated in place. The same ID is used to reuse a local image instead of downloading it again, and repeated records in one harvest are merged before download. Byte-identical images with different Google IDs can only be recognized after their bytes are available; the sync deduplicator then removes entries that also match on title, location, and caption.

---

## 🛠️ All CLI Commands

| Command | Description |
|---|---|
| `python3 manage.py sync <file.json>` | **⬅ Primary workflow.** Import, download, and rebuild in one shot |
| `python3 manage.py build` | Rebuild `index.html` from the current catalog |
| `python3 manage.py import-maps <file.json>` | Import harvested contributions without downloading or rebuilding |
| `python3 manage.py download-images` | Download remote CDN photos to local disk |
| `python3 manage.py add` | Interactive wizard — add a single entry with EXIF GPS detection |
| `python3 manage.py scan-inbox` | Batch-ingest photos dropped into `images/inbox/` |
| `python3 manage.py import-takeout <path>` | Import a Google Takeout archive folder with JSON sidecars |
| `python3 manage.py import-reviews` | Match Maps reviews to photos and apply as captions |
| `python3 manage.py deduplicate` | Remove entries with byte-identical image files |
| `python3 manage.py harvest-guide` | Print the browser harvester snippet for the console |

---

## 📁 Project Structure

```
QuestForSignsOfLife/
├── data/
│   └── photos.yaml          # Catalog — the single source of truth
├── images/
│   └── inbox/               # Drop photos here for scan-inbox
├── tools/
│   └── harvest_google_maps.html   # Browser harvester bookmarklet
├── build_gallery.py         # Generates index.html from photos.yaml
├── manage.py                # CLI tool (sync, import, build, add, …)
├── styles.css               # Portfolio stylesheet
└── index.html               # Generated — do not edit directly
```

---

## ✏️ Editing the Catalog Manually

The catalog lives in `data/photos.yaml`. Each entry looks like:

```yaml
photos:
  - id: santa-cruz-sign
    title: "Santa Cruz Sign"
    category: "Signs and Wonders"
    location: "Santa Cruz de Tenerife, Spain"
    maps_url: "https://www.google.com/maps/search/?api=1&query=Santa+Cruz+Sign"
    image_path: "https://lh3.googleusercontent.com/..."
    caption: "The iconic letters at the waterfront."
```

After editing, rebuild the gallery:

```bash
python3 manage.py build
```

### Categories & Routing Criteria

Photos are organized into three distinct collections based on the following criteria:

| Category | Routing Criteria & Keywords | Examples |
|---|---|---|
| **`Public Art & Sculptures`** | Physical artwork, standalone sculptures, statues, civic monuments, memorials, murals, and bronze street figures.<br><br>**Keywords:** `sculpture`, `statue`, `monument`, `memorial`, `mural`, `obra`, named statues (e.g. `el lector`, `el vecino`, `lenda`). | *"Arrival" Sculpture*, *"Fulcrum I"*, *"Friends"*, *Lincoln Memorial Sculpture*, *W.E.B Du Bois Monument*, *Statue of William Penn*, *El Vecino Curioso* |
| **`Signs and Wonders`** | City name/letter signs, landmark signage, photo-op typography, miniature doors, roadside curiosities, and quirky tourist installations.<br><br>**Keywords:** `sign`, `letras`, `i love`, `faro`, `tiny door`, novelty wonders. | *Letras Madrid*, *Letras "I Love Sevilla"*, *Santa Cruz Sign*, *Corozal sign*, *Placencia Sign*, *"FARO" Sign*, *Tiny Door Atlanta* |
| **`Travel Discoveries`** | Destinations, exploration spots, architecture, civic buildings, transit hubs, natural parks, and local culture/dining.<br><br>**Keywords:** `park`, `beach`, `lake`, `city hall`, `church`, `airport`, `station`, restaurants, cafes, and miscellaneous travel stops. | *Suwanee City Hall*, *Placencia SDA Church*, *Martin Luther King, Jr. Park*, *Longview Beach*, *Miami International Airport*, *Restaurante O Castelo* |

---

## 🌐 Refresh, review, and publish

The GitHub Action is **manual only** (`workflow_dispatch`); pushes and pull requests never trigger a build or deployment.

1. Harvest the latest Google Maps photos and reviews using the bookmarklet in `tools/harvest_google_maps.html`.
2. Run `python3 manage.py sync ~/Downloads/maps_contributions.json`. This imports and merges entries, downloads only images not already available locally, deduplicates matching photos, and rebuilds `index.html`.
3. Review the generated page locally, then commit the updated `data/photos.yaml` and `images/` to `main`. The Action will not run for that commit.
4. In GitHub, open **Actions → Review and deploy gallery → Run workflow** and manually start it on `main`.
5. Review the run summary and the `generated-gallery-preview` artifact. If the generated site differs from the last successful Pages deployment, approve the `github-pages` deployment to publish it. If there are no site differences, publishing is skipped.

The comparison uses the latest successful GitHub Pages deployment as its baseline, not the current commit. It reports added, removed, and changed site files plus an HTML diff; expected site changes do not fail validation. Failed runs include a stage-by-stage summary. The workflow never accesses Google Maps or downloads photos; harvesting and incremental image downloads happen locally in `sync`. The `github-pages` environment requires review from `@dwongk` and allows deployments from `main`; this gates publishing the generated site only, not code review.

GitHub Pages is configured to deploy through **GitHub Actions**. The portfolio is published at `https://dwongk.github.io/QuestForSignsOfLife/`.

The profile image is stored locally at `images/profile-avatar.png` so the Google-hosted profile image cannot change the site without a reviewed repository change.

---

## ⚙️ Requirements

- Python 3.9+ (standard library only — no `pip install` needed)
- PyYAML is used automatically if installed, but is not required
