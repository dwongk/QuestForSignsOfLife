# Google Maps Photography Portfolio — Quest for Signs of Life

A Python-generated static photography portfolio for GitHub Pages, designed for Google Maps Local Guides and urban explorers.

## Key Features
- **Zero-Friction Ingestion**: Auto-extracts GPS coordinates, dates, and locations from EXIF metadata.
- **Online Bootstrapping**: Import directly from your Google Maps profile contributions or Google Takeout JSON sidecars in seconds.
- **Hybrid Hosting**: Supports both local images (`images/...`) and remote Google CDN URLs (`https://lh3.googleusercontent.com/...`).
- **Zero External Dependencies**: Runs entirely on Python 3.9+ standard library.

---

## 🚀 Quick Bootstrapping: Pull Photos from Online Data

### Option A: Harvest from your Google Maps Profile (Fastest)
1. Open [`tools/harvest_google_maps.html`](tools/harvest_google_maps.html) in your browser and drag the **📸 Harvest Maps Photos** button to your bookmarks bar.
2. Go to your [Google Maps Profile Photos](https://maps.app.goo.gl/fho6S7iKjvquva9W6).
3. Click the bookmarklet. It extracts high-resolution Google CDN photo URLs, place names, and Maps links into `maps_contributions.json`.
4. Run:
   ```bash
   python3 manage.py import-maps ~/Downloads/maps_contributions.json
   ```
   *Your portfolio immediately displays your actual Google Maps photos with zero file downloading required.*

### Option B: Import from Google Takeout Archive
If you exported Google Photos or Google Maps contributions with `.json` sidecars via Google Takeout:
```bash
python3 manage.py import-takeout ~/Downloads/Takeout/Google\ Photos
```
This automatically parses descriptions (captions), GPS coordinates, timestamps, copies images, and creates the catalog.

---

## ⚡ Frictionless Entry Creation

### 1. Drop & Scan Inbox (Easiest for local photos)
Drop any number of photos into `images/inbox/` and run:
```bash
python3 manage.py scan-inbox
```
It reads EXIF GPS tags, generates Google Maps coordinate links, reverse-geocodes the location name, moves the photos to the appropriate collection folder, and updates the catalog.

### 2. Guided Interactive Assistant
Run the interactive CLI wizard:
```bash
python3 manage.py add
```
Prompts for inputs, detects EXIF metadata, auto-suggests categories and related photo IDs, and safely writes valid YAML.

### 3. Direct YAML Editing
You can also edit `data/photos.yaml` directly:
```yaml
photos:
  - id: fulcrum-i
    title: Fulcrum I
    category: Public Art & Sculptures
    location: Suwanee, Georgia
    maps_url: https://maps.app.goo.gl/go4mAoMH8g55Gfb47
    image_path: images/public-art/fulcrum-i.jpg
    caption: A closer look at balance and leverage.
    related:
      - friends-sculpture
```

---

## 🛠️ Management CLI Commands

| Command | Description |
|---|---|
| `python3 manage.py build` | Rebuilds `index.html` |
| `python3 manage.py add` | Interactive wizard with EXIF GPS detection |
| `python3 manage.py scan-inbox` | Batch-ingests photos from `images/inbox/` |
| `python3 manage.py import-maps <file.json>` | Imports harvested Google Maps contributions |
| `python3 manage.py import-takeout <path>` | Batch-imports Takeout folder with JSON sidecars |
| `python3 manage.py download-images` | Downloads any remote CDN photos to local disk |
| `python3 manage.py harvest-guide` | Displays the browser harvester instructions |

---

## 🌐 Publish on GitHub Pages
1. Push your repository to GitHub.
2. Go to **Settings → Pages** and choose **GitHub Actions** (or Deploy from branch `main`).
3. GitHub Pages deploys your portfolio automatically.
