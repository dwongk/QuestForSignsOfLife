#!/usr/bin/env python3
"""Generate index.html from data/photos.yaml using only the Python standard library.

Supports both local image paths and remote URLs (e.g. Google CDN, Google Photos).
Works out of the box with zero external dependencies (pure standard library),
while also leveraging PyYAML if installed in the environment.
"""
import html
import re
from collections import defaultdict
from pathlib import Path


def get_project_root() -> Path:
    """Resolve project root regardless of where script is invoked from."""
    current = Path(__file__).resolve().parent
    if (current / "data").exists() or (current / "styles.css").exists():
        return current
    if (current.parent / "data").exists() or (current.parent / "styles.css").exists():
        return current.parent
    return current


ROOT = get_project_root()


def esc(value) -> str:
    """HTML-escape a string safely."""
    return html.escape((str(value) if value is not None else "").strip(), quote=True)


def slugify(value: str) -> str:
    """Generate a clean URL-friendly slug."""
    return re.sub(r"[^a-z0-9-]+", "-", (value or "").lower()).strip("-") or "collection"


def is_remote_url(url: str) -> bool:
    """Check if the path is a remote URL (e.g., Google CDN, web URL)."""
    return url.startswith(("https://", "http://", "//"))


def parse_yaml_subset(text: str) -> list[dict]:
    """Parse a subset of YAML (lists, mappings, block scalars, comments) with 0 dependencies."""
    lines = text.splitlines()
    photos = []
    current_photo = None
    current_key = None
    scalar_mode = None
    scalar_lines = []
    scalar_indent = 0
    item_indent = None

    def clean_val(v: str):
        v = v.strip()
        if v.startswith('"') and v.endswith('"'):
            return v[1:-1].replace('\\"', '"')
        if v.startswith("'") and v.endswith("'"):
            return v[1:-1]
        return v

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()

        # Handle multiline scalar continuation ('>' or '|')
        if scalar_mode:
            cur_indent = len(line) - len(line.lstrip())
            if not stripped:
                scalar_lines.append("")
                continue
            if cur_indent > scalar_indent:
                scalar_lines.append(stripped)
                continue
            else:
                val = " ".join(scalar_lines) if scalar_mode == ">" else "\n".join(scalar_lines)
                if current_photo is not None and current_key:
                    current_photo[current_key] = val.strip()
                scalar_mode = None
                scalar_lines = []

        if not stripped or stripped.startswith("#"):
            continue

        cur_indent = len(line) - len(line.lstrip())

        # Skip top-level 'photos:' container header if present
        if stripped == "photos:":
            continue

        # New photo list item
        if stripped.startswith("- ") and (item_indent is None or cur_indent <= item_indent):
            item_indent = cur_indent
            current_photo = {}
            photos.append(current_photo)
            current_key = None
            rest = stripped[2:].strip()
            if not rest:
                continue
            if ":" in rest:
                k, v = rest.split(":", 1)
                k = k.strip()
                v = v.strip()
                current_key = k
                if v in (">", "|"):
                    scalar_mode = v
                    scalar_indent = cur_indent
                    scalar_lines = []
                elif v.startswith("[") and v.endswith("]"):
                    current_photo[k] = [clean_val(x) for x in v[1:-1].split(",") if x.strip()]
                elif v:
                    current_photo[k] = clean_val(v)
                else:
                    current_photo[k] = []
            continue

        # Sub-item inside a list field (e.g. under 'related:')
        if current_photo is not None and stripped.startswith("- ") and item_indent is not None and cur_indent > item_indent:
            val = clean_val(stripped[2:])
            if current_key:
                if not isinstance(current_photo.get(current_key), list):
                    current_photo[current_key] = []
                current_photo[current_key].append(val)
            continue

        # Regular key-value pair
        if current_photo is not None and ":" in stripped:
            k, v = stripped.split(":", 1)
            k = k.strip()
            v = v.strip()
            current_key = k
            if v in (">", "|"):
                scalar_mode = v
                scalar_indent = cur_indent
                scalar_lines = []
            elif v.startswith("[") and v.endswith("]"):
                current_photo[k] = [clean_val(x) for x in v[1:-1].split(",") if x.strip()]
            elif v:
                current_photo[k] = clean_val(v)
            else:
                current_photo[k] = []
            continue

    if scalar_mode and current_photo is not None and current_key:
        val = " ".join(scalar_lines) if scalar_mode == ">" else "\n".join(scalar_lines)
        current_photo[current_key] = val.strip()

    return photos


def load_photos(root: Path) -> list[dict]:
    """Load photos from photos.yaml (or photos.yml) with graceful fallback."""
    candidate_paths = [
        root / "data" / "photos.yaml",
        root / "data" / "photos.yml",
        root / "photos.yaml",
        root / "photos.yml",
    ]
    yaml_path = next((p for p in candidate_paths if p.is_file()), None)
    if not yaml_path:
        raise SystemExit(f"Catalog file not found. Checked: {', '.join(str(p) for p in candidate_paths)}")

    content = yaml_path.read_text(encoding="utf-8")
    try:
        import yaml
        data = yaml.safe_load(content)
        if isinstance(data, dict) and "photos" in data:
            return data["photos"] or []
        if isinstance(data, list):
            return data
    except ImportError:
        pass
    except Exception as e:
        print(f"Notice: PyYAML parser gave '{e}', falling back to built-in parser.")

    return parse_yaml_subset(content)


def normalize_photo(photo: dict, root: Path) -> dict:
    """Normalize fields, enforce types, and validate assets."""
    pid = str(photo.get("id") or "").strip()
    title = str(photo.get("title") or "Untitled").strip()
    if not pid:
        pid = slugify(title)

    category = str(photo.get("category") or "").strip()
    place_type = str(photo.get("place_type") or "").strip()
    if place_type:
        category = category_from_place_type(place_type)
    elif not category:
        category = "Travel Discoveries"
    location = str(photo.get("location") or "").strip()
    maps_url = str(photo.get("maps_url") or "").strip()
    image_path = str(photo.get("image_path") or "").strip()
    caption = str(photo.get("caption") or "").strip()

    raw_related = photo.get("related", [])
    if isinstance(raw_related, str):
        related = [x.strip() for x in raw_related.split(",") if x.strip()]
    elif isinstance(raw_related, list):
        related = [str(x).strip() for x in raw_related if str(x).strip()]
    else:
        related = []

    # Asset verification
    if image_path:
        if not is_remote_url(image_path):
            local_file = root / image_path
            if not local_file.is_file():
                print(f'Warning: local image file missing for {pid}: {image_path}')
    else:
        print(f'Warning: no image_path specified for {pid}')

    return {
        "id": pid,
        "title": title,
        "category": category,
        "location": location,
        "maps_url": maps_url,
        "image_path": image_path,
        "caption": caption,
        "related": related,
    }


def location_sort_key(location: str) -> str:
    """Extract zip/postal + city/state-country as a stable sort key."""
    parts = [p.strip() for p in location.split(',')]
    last = parts[-1] if parts else location
    second_last = parts[-2] if len(parts) >= 2 else ''
    # Search only the last two segments (avoids confusing building numbers with zip codes)
    last_two = ', '.join(parts[-2:]) if len(parts) >= 2 else location
    zip_matches = list(re.finditer(r'(?<!\d)(\d{4,5}(?:-\d{3,4})?)(?!\d)', last_two))
    postal = zip_matches[-1].group(1) if zip_matches else ''
    return f"{last}|{postal}|{second_last}".lower()


_SCULPTURE_TYPES = {"sculpture", "monument", "historical landmark", "mural", "memorial"}
_TOURIST_TYPES = {"tourist attraction", "point of interest"}


def category_from_place_type(place_type: str) -> str:
    pt = (place_type or "").lower()
    if any(t in pt for t in _SCULPTURE_TYPES):
        return "Public Art & Sculptures"
    if any(t in pt for t in _TOURIST_TYPES):
        return "Signs and Wonders"
    return "Travel Discoveries"


def main():
    raw_photos = load_photos(ROOT)
    if not raw_photos:
        raise SystemExit("No photo entries found in catalog.")

    photos = [normalize_photo(p, ROOT) for p in raw_photos]
    ids = {p["id"] for p in photos}
    categories = defaultdict(list)

    for i, photo in enumerate(photos):
        photo["_order"] = i  # preserve original import order for date-sort
        categories[photo["category"]].append(photo)
        for rid in photo["related"]:
            if rid not in ids:
                print(f'Warning: unknown related id "{rid}" in {photo["id"]}')

    # Custom category display order
    CATEGORY_ORDER = ["Public Art & Sculptures", "Signs and Wonders", "Travel Discoveries"]
    def category_sort_key(name):
        try:
            return CATEGORY_ORDER.index(name)
        except ValueError:
            return len(CATEGORY_ORDER)

    sections = []
    for category, items in sorted(categories.items(), key=lambda item: category_sort_key(item[0])):
        cards = []
        for photo in items:
            related_links = []
            for rid in photo["related"]:
                target = next((p for p in photos if p["id"] == rid), None)
                if target:
                    related_links.append(
                        f'<a href="#{esc(slugify(target["category"]))}">{esc(target["title"])}</a>'
                    )
            url = photo["maps_url"]
            map_link = ""
            if is_remote_url(url):
                map_link = (
                    f'<a class="map-link" href="{esc(url)}" target="_blank" '
                    f'rel="noopener noreferrer">View location on Google Maps</a>'
                )

            related_html = (
                f'<p class="related"><strong>Related:</strong> {" · ".join(related_links)}</p>'
                if related_links
                else ""
            )

            loc_html = f'<p class="location">{esc(photo["location"])}</p>' if photo["location"] else ""
            cap_html = f'<p>{esc(photo["caption"])}</p>' if photo["caption"] else ""

            data_loc = esc(photo["location"].lower())
            data_title = esc(photo["title"].lower())
            data_order = photo["_order"]
            loc_sort = esc(location_sort_key(photo["location"]))
            img_tag = f'<img src="{esc(photo["image_path"])}" alt="{esc(photo["title"])}" loading="lazy">'
            img_html = (
                f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{img_tag}</a>'
                if url else img_tag
            )

            cards.append(
                f'<article class="card" id="{esc(photo["id"])}" '
                f'data-title="{data_title}" data-location="{data_loc}" '
                f'data-location-sort="{loc_sort}" data-order="{data_order}">\n'
                f'  {img_html}\n'
                f'  <div class="card-body">\n'
                f'    <h3>{esc(photo["title"])}</h3>\n'
                f'    {loc_html}\n'
                f'    {cap_html}\n'
                f'    {map_link}\n'
                f'    {related_html}\n'
                f'  </div>\n'
                f'</article>'
            )

        sections.append(
            f'<section class="collection" id="{esc(slugify(category))}">\n'
            f'  <h2>{esc(category)}</h2>\n'
            f'  <div class="grid">\n{"".join(cards)}\n</div>\n'
            f'</section>'
        )

    nav = " ".join(
        f'<a href="#{esc(slugify(category))}">{esc(category)}</a>'
        for category in sorted(categories, key=category_sort_key)
    )

    sort_js = """
<script>
(function () {
  const select = document.getElementById('sort-select');
  if (!select) return;
  function applySort(mode) {
    document.querySelectorAll('.collection .grid').forEach(function (grid) {
      const cards = Array.from(grid.querySelectorAll('.card'));
      cards.sort(function (a, b) {
        if (mode === 'title')    return a.dataset.title.localeCompare(b.dataset.title);
        if (mode === 'location') return a.dataset.locationSort.localeCompare(b.dataset.locationSort);
        return parseInt(a.dataset.order) - parseInt(b.dataset.order); // date (original order)
      });
      cards.forEach(function (c) { grid.appendChild(c); });
    });
  }
  select.addEventListener('change', function () { applySort(this.value); });
  applySort(select.value);
}());
</script>"""

    bio = "Seeking signs. Striking poses. Collecting stories. 🌍📸 I take landmarks personally, statues figuratively, and scenic routes seriously. Just following the signs wherever they lead."
    avatar_url = "https://lh3.googleusercontent.com/a-/ALV-UjVYVIkcfhjpvwHBjh4CRCGBfYFcAwky-aN633ZvB7PXFvePnV8=s96-c"
    profile_url = "https://maps.app.goo.gl/fho6S7iKjvquva9W6"

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{esc(bio)}">
<title>Quest For Signs Of Life</title>
<link rel="stylesheet" href="styles.css">
</head>
<body>
<header class="hero">
  <img class="profile-avatar" src="{esc(avatar_url)}" alt="Quest For Signs Of Life" width="80" height="80">
  <h1>Quest For Signs Of Life</h1>
  <p>{esc(bio)}</p>
  <p class="profile-link"><a href="{esc(profile_url)}" target="_blank" rel="noopener noreferrer">View on Google Maps</a></p>
</header>
<div class="sort-bar">
  <label for="sort-select">Sort by:</label>
  <select id="sort-select">
    <option value="location" selected>Location (Zip/Region)</option>
    <option value="title">Title (A–Z)</option>
    <option value="date">Date Added</option>
  </select>
</div>
<nav class="collection-nav" aria-label="Photo collections">{nav}</nav>
<main>{"".join(sections)}</main>
<footer><p>Photos and captions are curated for this portfolio. Location links open Google Maps.</p></footer>
{sort_js}
</body>
</html>
"""
    output_path = ROOT / "index.html"
    output_path.write_text(page, encoding="utf-8")
    print(f"Generated {output_path}")
    print(f"Processed {len(photos)} photo records across {len(categories)} collections.")


if __name__ == "__main__":
    main()
