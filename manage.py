#!/usr/bin/env python3
"""Manage QuestForSignsOfLife portfolio:
- build: Rebuild index.html
- add: Interactive wizard with EXIF GPS detection
- import-takeout: Batch-import Google Takeout folder with JSON sidecars
- import-maps: Batch-import Google Maps profile contributions JSON
- download-images: Download remote CDN images locally
- scan-inbox: Ingest newly dropped photos from an inbox folder
- harvest-guide: Instructions and bookmarklet code to harvest Google Maps
"""
import argparse
import json
import os
import re
import struct
import sys
import urllib.parse
import urllib.request
from pathlib import Path

# Import gallery generator functions from root build_gallery.py
import build_gallery

ROOT = build_gallery.ROOT
DATA_FILE = ROOT / "data" / "photos.yaml"
IMAGES_DIR = ROOT / "images"


# ---------------------------------------------------------------------------
# EXIF Extraction (Pure standard library, zero dependencies)
# ---------------------------------------------------------------------------

def extract_exif(filepath: Path) -> dict:
    """Extract GPS coordinates and date taken from JPEG files using pure standard library."""
    meta = {"latitude": None, "longitude": None, "date_taken": None}
    try:
        with filepath.open("rb") as f:
            header = f.read(2)
            if header != b"\xff\xd8":
                return meta
            data = f.read(131072)  # Read up to 128KB for APP1 EXIF segment

        idx = 0
        app1_data = None
        while idx < len(data) - 4:
            if data[idx] != 0xFF:
                break
            marker = data[idx + 1]
            idx += 2
            length = struct.unpack(">H", data[idx:idx + 2])[0]
            if marker == 0xE1:  # APP1 Marker
                app1_data = data[idx + 2: idx + length]
                break
            idx += length

        if not app1_data or not app1_data.startswith(b"Exif\x00\x00"):
            return meta

        tiff = app1_data[6:]
        if len(tiff) < 8:
            return meta
        endian = "<" if tiff[:2] == b"II" else ">"
        if tiff[2:4] not in (b"\x2a\x00", b"\x00\x2a"):
            return meta

        first_ifd_offset = struct.unpack(endian + "I", tiff[4:8])[0]

        def read_ifd(offset: int) -> dict:
            tags = {}
            if offset + 2 > len(tiff):
                return tags
            count = struct.unpack(endian + "H", tiff[offset:offset + 2])[0]
            pos = offset + 2
            for _ in range(count):
                if pos + 12 > len(tiff):
                    break
                tag, dtype, cnt = struct.unpack(endian + "HHI", tiff[pos:pos + 8])
                val_bytes = tiff[pos + 8:pos + 12]
                pos += 12
                tags[tag] = (dtype, cnt, val_bytes)
            return tags

        def get_rational(offset: int) -> float:
            if offset + 8 > len(tiff):
                return 0.0
            num, den = struct.unpack(endian + "II", tiff[offset:offset + 8])
            return num / den if den != 0 else 0.0

        ifd0 = read_ifd(first_ifd_offset)

        # Tag 0x0132 = DateTime
        if 0x0132 in ifd0:
            dtype, cnt, val_bytes = ifd0[0x0132]
            off = struct.unpack(endian + "I", val_bytes)[0]
            if off + cnt <= len(tiff):
                dt_str = tiff[off:off + cnt].decode("ascii", errors="ignore").strip("\x00")
                meta["date_taken"] = dt_str

        # Tag 0x8825 = GPSInfo IFD
        if 0x8825 in ifd0:
            gps_offset = struct.unpack(endian + "I", ifd0[0x8825][2])[0]
            gps_tags = read_ifd(gps_offset)

            def parse_dms(entry) -> float:
                dtype, cnt, val_bytes = entry
                off = struct.unpack(endian + "I", val_bytes)[0]
                d = get_rational(off)
                m = get_rational(off + 8)
                s = get_rational(off + 16)
                return d + (m / 60.0) + (s / 3600.0)

            lat_ref_entry = gps_tags.get(1)
            lat_val_entry = gps_tags.get(2)
            lon_ref_entry = gps_tags.get(3)
            lon_val_entry = gps_tags.get(4)

            lat = None
            lon = None
            if lat_val_entry and lat_ref_entry:
                ref_char = chr(lat_ref_entry[2][0]).upper()
                lat = parse_dms(lat_val_entry)
                if ref_char == "S":
                    lat = -lat
            if lon_val_entry and lon_ref_entry:
                ref_char = chr(lon_ref_entry[2][0]).upper()
                lon = parse_dms(lon_val_entry)
                if ref_char == "W":
                    lon = -lon

            if lat is not None and lon is not None:
                meta["latitude"] = round(lat, 6)
                meta["longitude"] = round(lon, 6)

    except Exception:
        pass
    return meta


def reverse_geocode(lat: float, lon: float) -> str:
    """Attempt reverse geocoding via OpenStreetMap Nominatim with safe offline fallback."""
    try:
        url = (
            f"https://nominatim.openstreetmap.org/reverse"
            f"?format=json&lat={lat}&lon={lon}&zoom=14&addressdetails=1"
        )
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "QuestForSignsOfLife-Portfolio/1.0 (local guide catalog)"},
        )
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            addr = data.get("address", {})
            city = (
                addr.get("city")
                or addr.get("town")
                or addr.get("village")
                or addr.get("suburb")
                or addr.get("county")
                or ""
            )
            state = addr.get("state") or addr.get("country") or ""
            if city and state:
                return f"{city}, {state}"
            return city or state or ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# YAML Helpers
# ---------------------------------------------------------------------------

def photo_to_yaml(photo: dict) -> str:
    """Format a single photo entry as valid YAML with clean indenting."""
    lines = [f"  - id: {photo['id']}"]
    lines.append(f"    title: {json.dumps(photo.get('title', 'Untitled'))}")
    lines.append(f"    category: {json.dumps(photo.get('category', 'Uncategorized'))}")
    if photo.get("location"):
        lines.append(f"    location: {json.dumps(photo['location'])}")
    if photo.get("maps_url"):
        lines.append(f"    maps_url: {json.dumps(photo['maps_url'])}")
    lines.append(f"    image_path: {json.dumps(photo.get('image_path', ''))}")

    caption = (photo.get("caption") or "").strip()
    if "\n" in caption:
        lines.append("    caption: >")
        for cline in caption.splitlines():
            lines.append(f"      {cline.strip()}")
    elif caption:
        lines.append(f"    caption: {json.dumps(caption)}")
    else:
        lines.append('    caption: ""')

    related = photo.get("related", [])
    if isinstance(related, str):
        related = [x.strip() for x in related.split(",") if x.strip()]
    if related:
        lines.append("    related:")
        for r in related:
            lines.append(f"      - {r}")
    else:
        lines.append("    related: []")
    return "\n".join(lines)


def get_photo_fingerprint(p: dict) -> str:
    """Extract a unique identity for a photo (by CDN photo ID or normalized local path)."""
    img = p.get("image_path") or p.get("image_url") or ""
    # Extract unique Google CDN key if present (e.g. /gps-cs/<KEY>=... or /grass-cs/<KEY>=... or /p/<KEY>=...)
    for prefix in ["/gps-cs/", "/grass-cs/", "/p/"]:
        if prefix in img:
            part = img.split(prefix)[1]
            return part.split("=")[0].split("/")[0]
    return img.strip().lower()


def upsert_photos(incoming_photos: list[dict]):
    """Update existing entries or insert new ones based on photo identity, preventing duplicates."""
    if not incoming_photos:
        return

    existing = build_gallery.load_photos(ROOT) if DATA_FILE.exists() else []

    # Map existing photos by their fingerprint
    existing_by_fp = {}
    for p in existing:
        fp = get_photo_fingerprint(p)
        if fp:
            existing_by_fp[fp] = p

    existing_ids = {p.get("id") for p in existing}
    updated_count = 0
    added_count = 0
    merged = list(existing)

    for inc in incoming_photos:
        fp = get_photo_fingerprint(inc)
        if fp and fp in existing_by_fp:
            # UPDATE existing entry!
            target = existing_by_fp[fp]
            if inc.get("title") and inc["title"] != "Photo Discovery":
                target["title"] = inc["title"]
            if inc.get("location"):
                target["location"] = inc["location"]
            if inc.get("maps_url"):
                target["maps_url"] = inc["maps_url"]
            if inc.get("category"):
                target["category"] = inc["category"]
            # Preserve existing user caption and related if target has them
            if inc.get("caption") and not target.get("caption"):
                target["caption"] = inc["caption"]
            if inc.get("related") and not target.get("related"):
                target["related"] = inc["related"]
            updated_count += 1
        else:
            # INSERT new entry!
            base_id = build_gallery.slugify(inc.get("title") or "photo")
            pid = base_id
            counter = 2
            while pid in existing_ids:
                pid = f"{base_id}-{counter}"
                counter += 1
            inc["id"] = pid
            existing_ids.add(pid)
            if fp:
                existing_by_fp[fp] = inc
            merged.append(inc)
            added_count += 1

    content = "# Photography Discoveries Catalog\n# Curated from Google Maps Local Guide contributions\n\nphotos:\n"
    content += "\n\n".join(photo_to_yaml(p) for p in merged) + "\n"
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(content, encoding="utf-8")

    print(f"Catalog sync complete: {updated_count} updated, {added_count} added ({len(merged)} total).")


def append_photos(new_photos: list[dict]):
    """Compatibility wrapper delegating to upsert_photos."""
    upsert_photos(new_photos)


# ---------------------------------------------------------------------------
# CLI Commands
# ---------------------------------------------------------------------------

def cmd_build(args):
    """Rebuild index.html."""
    build_gallery.main()


def cmd_add(args):
    """Interactive wizard to create a photo entry with EXIF auto-detection."""
    print("=== Add New Photography Entry ===")
    img_input = input("Image path or remote URL: ").strip()
    if not img_input:
        print("Error: Image path or URL is required.")
        return

    detected_gps = None
    detected_date = None
    local_path = None

    if not build_gallery.is_remote_url(img_input):
        candidate = Path(img_input).expanduser()
        if not candidate.is_file():
            # Try resolving relative to ROOT
            candidate = ROOT / img_input
        if candidate.is_file():
            local_path = candidate
            exif_data = extract_exif(candidate)
            if exif_data.get("latitude") and exif_data.get("longitude"):
                detected_gps = (exif_data["latitude"], exif_data["longitude"])
                print(f" Detected GPS: {detected_gps[0]}, {detected_gps[1]}")
            if exif_data.get("date_taken"):
                detected_date = exif_data["date_taken"]
                print(f" Detected Date: {detected_date}")

    # Title
    default_title = local_path.stem.replace("_", " ").title() if local_path else "Discovery"
    title = input(f"Title [{default_title}]: ").strip() or default_title
    suggested_id = build_gallery.slugify(title)
    photo_id = input(f"Unique ID [{suggested_id}]: ").strip() or suggested_id

    # Existing categories
    existing_photos = build_gallery.load_photos(ROOT) if DATA_FILE.exists() else []
    cats = sorted(list({p.get("category") for p in existing_photos if p.get("category")}))
    if cats:
        print("Existing categories:")
        for idx, c in enumerate(cats, 1):
            print(f"  {idx}. {c}")
        cat_choice = input("Category number or enter new category: ").strip()
        if cat_choice.isdigit() and 1 <= int(cat_choice) <= len(cats):
            category = cats[int(cat_choice) - 1]
        else:
            category = cat_choice or "Public Art & Sculptures"
    else:
        category = input("Category [Public Art & Sculptures]: ").strip() or "Public Art & Sculptures"

    # Location & Maps URL
    suggested_loc = ""
    suggested_maps = ""
    if detected_gps:
        suggested_loc = reverse_geocode(detected_gps[0], detected_gps[1])
        suggested_maps = f"https://www.google.com/maps?q={detected_gps[0]},{detected_gps[1]}"

    loc_prompt = f"Location [{suggested_loc}]: " if suggested_loc else "Location (e.g. Suwanee, Georgia): "
    location = input(loc_prompt).strip() or suggested_loc

    maps_prompt = f"Google Maps URL [{suggested_maps}]: " if suggested_maps else "Google Maps URL (or leave blank): "
    maps_url = input(maps_prompt).strip() or suggested_maps

    caption = input("Caption: ").strip()

    # Related items
    related = []
    if existing_photos:
        print("Select related photos (comma-separated numbers or leave blank):")
        for idx, ep in enumerate(existing_photos[:12], 1):
            print(f"  {idx}. {ep['title']} ({ep['id']})")
        rel_in = input("Related choice: ").strip()
        if rel_in:
            for part in rel_in.split(","):
                part = part.strip()
                if part.isdigit() and 1 <= int(part) <= len(existing_photos):
                    related.append(existing_photos[int(part) - 1]["id"])
                elif part:
                    related.append(part)

    # Save image to images directory if local
    final_image_path = img_input
    if local_path and not str(local_path).startswith(str(ROOT / "images")):
        cat_slug = build_gallery.slugify(category)
        target_dir = IMAGES_DIR / cat_slug
        target_dir.mkdir(parents=True, exist_ok=True)
        dest_filename = f"{photo_id}{local_path.suffix.lower() or '.jpg'}"
        dest_file = target_dir / dest_filename
        dest_file.write_bytes(local_path.read_bytes())
        final_image_path = f"images/{cat_slug}/{dest_filename}"
        print(f" Copied image to {final_image_path}")

    entry = {
        "id": photo_id,
        "title": title,
        "category": category,
        "location": location,
        "maps_url": maps_url,
        "image_path": final_image_path,
        "caption": caption,
        "related": related,
    }

    append_photos([entry])
    build_gallery.main()


def cmd_import_takeout(args):
    """Batch-import photos and JSON sidecars from a Google Takeout export directory."""
    takeout_path = Path(args.path).expanduser().resolve()
    if not takeout_path.is_dir():
        print(f"Error: Directory not found: {takeout_path}")
        return

    print(f"Scanning Google Takeout folder: {takeout_path}")
    image_exts = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
    new_entries = []

    # Find all sidecar .json files
    json_files = list(takeout_path.rglob("*.json"))
    print(f"Found {len(json_files)} metadata JSON sidecars.")

    for jpath in json_files:
        try:
            with jpath.open("r", encoding="utf-8", errors="ignore") as f:
                data = json.load(f)
        except Exception:
            continue

        # Look for corresponding image file
        # Google Takeout pairs e.g. "photo.jpg.json" with "photo.jpg"
        candidate_img_name = jpath.name[:-5]  # strip .json
        img_file = jpath.with_name(candidate_img_name)
        if not img_file.is_file() and img_file.suffix.lower() not in image_exts:
            # Try matching with title in json
            json_title = data.get("title", "")
            if json_title:
                alt = jpath.with_name(json_title)
                if alt.is_file():
                    img_file = alt

        if not img_file.is_file():
            continue

        title = data.get("title") or img_file.stem.replace("_", " ").title()
        caption = data.get("description", "").strip()

        # GPS data
        geo = data.get("geoData") or data.get("geoDataExif") or {}
        lat = geo.get("latitude", 0.0)
        lon = geo.get("longitude", 0.0)
        maps_url = ""
        location = ""
        if abs(lat) > 0.0001 or abs(lon) > 0.0001:
            maps_url = f"https://www.google.com/maps?q={lat},{lon}"
            location = reverse_geocode(lat, lon)

        cat = args.category or "Travel Discoveries"
        cat_slug = build_gallery.slugify(cat)
        slug_id = build_gallery.slugify(img_file.stem)

        # Copy image if requested or into project images folder
        target_dir = IMAGES_DIR / cat_slug
        target_dir.mkdir(parents=True, exist_ok=True)
        dest_filename = f"{slug_id}{img_file.suffix.lower()}"
        dest_file = target_dir / dest_filename
        if not dest_file.exists():
            dest_file.write_bytes(img_file.read_bytes())

        new_entries.append({
            "id": slug_id,
            "title": title,
            "category": cat,
            "location": location,
            "maps_url": maps_url,
            "image_path": f"images/{cat_slug}/{dest_filename}",
            "caption": caption,
            "related": [],
        })

    if not new_entries:
        print("No matching images with sidecars found.")
        return

    print(f"Found {len(new_entries)} valid photo entries with Takeout metadata.")
    append_photos(new_entries)
    build_gallery.main()


KNOWN_ADDR_TITLES = {
    "3913 savannah": "Fulcrum I Sculpture",
    "near 340, town center": "Hammer & Nails Suwanee",
    "5901 peachtree": "Peachtree Dentures and Implants",
    "atlanta, ga 30306": "Steel Columns Sculpture",
    "231 main st": "W.E.B Du Bois Monument",
    "autop. de circunvalación": "Letras Madrid",
    "plaza de españa": "Santa Cruz Sign",
    "pl. de la encarnación": 'Letras "I Love Sevilla"',
    "praça dom francisco": '"FARO" Sign',
    "woodland ave": "Martin Luther King, Jr. Park",
    "gjfj+vqf": "Placencia Sign",
    "gjcj+f35": "Placencia SDA Church",
    "2494 meme's place": "MeMe's Place",
    "meme's place": "MeMe's Place",
    "xq8j+68m": "Alejo Beni Park",
    "xpfg+w3m": "Mexicana",
    "coastal hwy": "Barber Sharps's Shop",
    "12 ganey st": "Dangriga Post Office",
}


def resolve_title_from_address(addr: str, idx: int = 0) -> str:
    """Resolve place title from address when title is defaulted to 'Photo Discovery'."""
    a_lower = (addr or "").lower()
    if "330 town center" in a_lower:
        return "Friends Sculpture" if idx in (3, 4) else "Suwanee City Hall"
    if "530 highland station" in a_lower:
        return "Gwinnett Dental Studio - Dr Titus Wongk"
    for key, name in KNOWN_ADDR_TITLES.items():
        if key in a_lower:
            return name
    return ""


def sanitize_harvested_items(items: list, default_cat: str) -> list:
    """Sanitize harvested items, stripping bloated profile text and isolating actual photos."""
    clean = []
    for i, it in enumerate(items):
        u = it.get("image_url") or it.get("image_path") or ""
        # Filter out avatars
        if any(x in u for x in ["/a-/", "/a/", "default-user"]):
            continue

        title = str(it.get("title") or "").strip()
        location = str(it.get("location") or "").strip()

        # If title contains profile dump or defaulted to Photo Discovery, resolve it!
        if not title or title == "Photo Discovery" or "Local Guide" in title or len(title) > 60:
            resolved = resolve_title_from_address(location, i)
            if resolved:
                title = resolved
            elif "Local Guide" in title:
                title = "Photo Discovery"

        category = it.get("category") or default_cat
        comb = (title + " " + location).lower()
        if any(w in comb for w in ["sign", "letras", "faro"]):
            category = "Signs and Wonders"
        elif any(w in comb for w in ["spain", "belize", "portugal", "madrid", "sevilla", "park", "church", "mexicana"]):
            category = "Travel Discoveries"
        elif any(w in comb for w in ["sculpture", "statue", "monument", "art", "mural"]):
            category = "Public Art & Sculptures"

        maps_url = it.get("maps_url") or ""
        if (not maps_url or "contrib" in maps_url) and title and title != "Photo Discovery":
            maps_url = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote_plus(title + ' ' + location)}"

        clean.append({
            "title": title or "Photo Discovery",
            "location": location,
            "image_url": u,
            "maps_url": maps_url,
            "category": category,
        })

    return clean


def cmd_import_maps(args):
    """Import photos harvested from Google Maps Profile contributions JSON."""
    json_path = Path(args.json_file).expanduser().resolve()
    if not json_path.is_file():
        print(f"Error: Harvest file not found: {json_path}")
        return

    with json_path.open("r", encoding="utf-8") as f:
        items = json.load(f)

    if not isinstance(items, list):
        print("Error: Expected a JSON array of photo entries.")
        return

    default_cat = args.category or "Public Art & Sculptures"
    items = sanitize_harvested_items(items, default_cat)
    print(f"Processing {len(items)} clean photo contribution(s) from {json_path.name}")
    new_entries = []

    for it in items:
        title = (it.get("title") or "Photo Discovery").strip()
        slug_id = build_gallery.slugify(title)
        img_url = it.get("image_url") or it.get("image_path") or ""
        maps_url = it.get("maps_url") or ""
        location = it.get("location") or ""
        caption = it.get("caption") or ""
        category = it.get("category") or default_cat

        if not img_url:
            continue

        new_entries.append({
            "id": slug_id,
            "title": title,
            "category": category,
            "location": location,
            "maps_url": maps_url,
            "image_path": img_url,
            "caption": caption,
            "related": it.get("related", []),
        })

    append_photos(new_entries)
    build_gallery.main()


def cmd_download_images(args):
    """Download any remote CDN images listed in photos.yaml to local images/ directory."""
    photos = build_gallery.load_photos(ROOT)
    remote_photos = [p for p in photos if build_gallery.is_remote_url(p.get("image_path", ""))]

    if not remote_photos:
        print("No remote image URLs found in photos.yaml. All photos are already local.")
        return

    print(f"Downloading {len(remote_photos)} remote image(s) to local storage...")
    content = DATA_FILE.read_text(encoding="utf-8")

    for p in remote_photos:
        url = p["image_path"]
        cat_slug = build_gallery.slugify(p.get("category", "uncategorized"))
        target_dir = IMAGES_DIR / cat_slug
        target_dir.mkdir(parents=True, exist_ok=True)
        dest_filename = f"{p['id']}.jpg"
        dest_path = target_dir / dest_filename

        try:
            print(f" Downloading {p['title']} -> {dest_path.relative_to(ROOT)}...")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                dest_path.write_bytes(resp.read())
            # Replace URL with local path in catalog
            local_rel = f"images/{cat_slug}/{dest_filename}"
            content = content.replace(f'"{url}"', f'"{local_rel}"').replace(url, local_rel)
        except Exception as e:
            print(f"  Warning: failed to download {url}: {e}")

    DATA_FILE.write_text(content, encoding="utf-8")
    print("Catalog updated with local image paths.")
    build_gallery.main()


def cmd_scan_inbox(args):
    """Scan images/inbox for dropped photos and import them with EXIF metadata."""
    inbox_dir = ROOT / "images" / "inbox"
    if not inbox_dir.is_dir():
        inbox_dir.mkdir(parents=True, exist_ok=True)
        print(f"Created inbox folder at {inbox_dir.relative_to(ROOT)}.")
        print("Drop JPG or PNG images into that folder and re-run this command.")
        return

    files = [
        f for f in inbox_dir.iterdir()
        if f.is_file() and f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    ]
    if not files:
        print(f"No image files found in {inbox_dir.relative_to(ROOT)}.")
        print("Drop images there to batch import them.")
        return

    print(f"Found {len(files)} image(s) in inbox.")
    new_entries = []
    default_cat = args.category or "Public Art & Sculptures"
    cat_slug = build_gallery.slugify(default_cat)
    target_dir = IMAGES_DIR / cat_slug
    target_dir.mkdir(parents=True, exist_ok=True)

    for img in sorted(files):
        exif = extract_exif(img)
        title = img.stem.replace("_", " ").replace("-", " ").title()
        slug_id = build_gallery.slugify(title)

        maps_url = ""
        location = ""
        if exif.get("latitude") and exif.get("longitude"):
            lat, lon = exif["latitude"], exif["longitude"]
            maps_url = f"https://www.google.com/maps?q={lat},{lon}"
            location = reverse_geocode(lat, lon)

        dest_file = target_dir / f"{slug_id}{img.suffix.lower()}"
        img.rename(dest_file)

        new_entries.append({
            "id": slug_id,
            "title": title,
            "category": default_cat,
            "location": location,
            "maps_url": maps_url,
            "image_path": f"images/{cat_slug}/{dest_file.name}",
            "caption": f"Captured on {exif['date_taken']}" if exif.get("date_taken") else "",
            "related": [],
        })
        print(f" Ingested {title} (GPS: {exif.get('latitude')}, {exif.get('longitude')})")

    append_photos(new_entries)
    build_gallery.main()


def cmd_harvest_guide(args):
    """Show guide and JavaScript snippet to harvest Google Maps contributions."""
    snippet = """(async () => {
  console.log("%c[Harvester v4] Starting extraction...", "color: #135e58; font-weight: bold; font-size: 14px;");

  // 1. Ensure on Photos tab
  if (!location.href.includes('/photos')) {
    const pt = Array.from(document.querySelectorAll('button, [role="tab"], a')).find(t => (t.textContent || '').trim().toLowerCase() === 'photos');
    if (pt) { pt.click(); await new Promise(r => setTimeout(r, 2000)); }
  }

  // 2. Find scrollable photos pane
  let sp = null;
  for (const d of document.querySelectorAll('div')) {
    const s = window.getComputedStyle(d);
    if ((s.overflowY === 'auto' || s.overflowY === 'scroll') && d.scrollHeight > d.clientHeight + 50) {
      if ((d.textContent || '').includes('Date') || (d.textContent || '').includes('37')) {
        sp = d; break;
      }
    }
  }
  sp = sp || document.querySelector('div[role="main"]') || document.body;

  console.log("[Harvester] Scrolling photo list to load cards...");
  let lh = 0;
  for (let i = 0; i < 15; i++) {
    sp.scrollTop = sp.scrollHeight;
    await new Promise(r => setTimeout(r, 500));
    if (sp.scrollHeight === lh && i > 4) break;
    lh = sp.scrollHeight;
  }

  const clean = (raw) => {
    if (!raw) return null;
    const m = raw.match(/https?:\\/\\/[^"\'\\)\\s]+/);
    if (!m) return null;
    const u = m[0];
    if (/(\\/a\\/|\\/ogw\\/|default-user|avatar)/i.test(u)) return null;
    if (/(googleusercontent\\.com|ggpht\\.com|googleapis\\.com)/i.test(u)) {
      if (/(\\/p\\/|gps-proxy|gps-cs|grass-cs|=w|=s|=h)/i.test(u)) {
        return u.split('=')[0] + '=s1600';
      }
    }
    return null;
  };

  const seen = new Set();
  const cand = Array.from(sp.querySelectorAll('img, [style*="url("], div[role="img"]'));
  const pes = [];

  for (const el of cand) {
    // Skip small place cover icons (< 65px) and avatars
    const rect = el.getBoundingClientRect();
    if (rect.width > 0 && rect.width < 65) continue;

    let raw = el.tagName === 'IMG'
      ? (el.currentSrc || el.src || el.getAttribute('data-src'))
      : (el.getAttribute('style') || window.getComputedStyle(el).backgroundImage);

    const high = clean(raw);
    if (!high || seen.has(high) || high.includes('/a-/')) continue;
    seen.add(high);
    pes.push({ el, url: high });
  }

  const items = [];
  for (const { el, url } of pes) {
    let curr = el, card = el;
    while (curr && curr.parentElement && curr.parentElement !== sp && curr.parentElement !== document.body) {
      const p = curr.parentElement;
      const txt = (p.textContent || '').trim();
      if (txt.includes('Local Guide') || txt.includes('Edit profile') || txt.length > 280) break;
      card = p; curr = p;
    }

    let ael = card.querySelector('[class*="fontBody"], [class*="address"], [class*="caption"]');
    let loc = (ael?.textContent || '').trim();

    let title = '';
    // Check previous sibling of address element
    if (ael && ael.previousElementSibling) {
      title = (ael.previousElementSibling.textContent || '').trim();
    }
    // Check header text minus address text
    if ((!title || title.length > 60) && ael && ael.parentElement) {
      const ptxt = (ael.parentElement.textContent || '').trim();
      if (loc && ptxt.includes(loc)) {
        title = ptxt.replace(loc, '').trim();
      }
    }
    // Backwards traversal for shared place headers
    if (!title || title.includes('Local Guide') || title.length > 60) {
      let prev = card;
      while (prev) {
        prev = prev.previousElementSibling || prev.parentElement;
        if (!prev || prev === sp || prev === document.body) break;
        const prevAel = prev.querySelector?.('[class*="fontBody"], [class*="address"]');
        if (prevAel) {
          if (!loc) loc = (prevAel.textContent || '').trim();
          if (prevAel.previousElementSibling) {
            title = (prevAel.previousElementSibling.textContent || '').trim();
          } else if (prevAel.parentElement) {
            title = (prevAel.parentElement.textContent || '').replace(prevAel.textContent || '', '').trim();
          }
        }
        if (!title) {
          const ct = prev.querySelector?.('[class*="fontHeadline"], [class*="title"], h1, h2, h3')?.textContent?.trim();
          if (ct && !ct.includes('Local Guide') && ct.length < 60) title = ct;
        }
        if (title && !title.includes('Local Guide') && title.length < 60) break;
      }
    }

    title = title.replace(/^/, '').replace(/.*/, '').replace(/.*/, '').replace(/\\s+/g, ' ').trim();
    loc = loc.replace(/^/, '').replace(/.*/, '').replace(/.*/, '').replace(/\\s+/g, ' ').trim();

    if (!title || title.includes('Local Guide') || title.length > 60) {
      title = 'Photo Discovery';
    }

    const comb = (title + ' ' + loc).toLowerCase();
    const cat = /(sign|letras|faro)/i.test(comb)
      ? 'Signs and Wonders'
      : /(spain|belize|portugal|madrid|sevilla|church|park|mexicana)/i.test(comb)
        ? 'Travel Discoveries'
        : 'Public Art & Sculptures';

    const mapUrl = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(title + (loc ? ' ' + loc : ''))}`;

    items.push({
      title: title,
      location: loc,
      image_url: url,
      maps_url: mapUrl,
      category: cat
    });
  }

  const finalItems = items.slice(0, 37);
  console.log(`%c[Harvester] Extracted ${finalItems.length} photos!`, "color: #135e58; font-weight: bold; font-size: 14px;");

  const blob = new Blob([JSON.stringify(finalItems, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "maps_contributions.json";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  console.log("%c✓ Successfully downloaded maps_contributions.json with clean titles!", "color: green; font-weight: bold;");
})();"""

    print("=" * 70)
    print("GOOGLE MAPS PROFILE HARVEST GUIDE (v4.0 Smart-Sync)")
    print("=" * 70)
    print("\n1. Open Chrome/Safari and visit your Google Maps Profile Photos directly:")
    print("   https://www.google.com/maps/contrib/109844961042142282833/photos")
    print("\n2. Press Cmd+Option+J (Mac) or Ctrl+Shift+J (Windows) to open the Console.")
    print("\n3. Paste the following JavaScript snippet and press Enter:\n")
    print("-" * 70)
    print(snippet)
    print("-" * 70)
    print("\n4. It will auto-download 'maps_contributions.json'.")
    print("5. Run: python3 manage.py import-maps ~/Downloads/maps_contributions.json")
    print("   (Existing photos are recognized and updated without creating duplicates)")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="QuestForSignsOfLife Management & Bootstrapping Tool"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # build
    subparsers.add_parser("build", help="Rebuild the static portfolio (index.html)")

    # add
    subparsers.add_parser("add", help="Interactive entry creation wizard with EXIF GPS")

    # import-takeout
    p_takeout = subparsers.add_parser("import-takeout", help="Import Google Takeout folder with JSON sidecars")
    p_takeout.add_argument("path", help="Path to unzipped Takeout Google Photos folder")
    p_takeout.add_argument("--category", default="Travel Discoveries", help="Default category")

    # import-maps
    p_maps = subparsers.add_parser("import-maps", help="Import Google Maps contributions JSON")
    p_maps.add_argument("json_file", help="Path to maps_contributions.json")
    p_maps.add_argument("--category", default="Public Art & Sculptures", help="Default category")

    # download-images
    subparsers.add_parser("download-images", help="Download remote CDN photos locally")

    # scan-inbox
    p_inbox = subparsers.add_parser("scan-inbox", help="Ingest dropped photos from images/inbox")
    p_inbox.add_argument("--category", default="Public Art & Sculptures", help="Category for inbox photos")

    # harvest-guide
    subparsers.add_parser("harvest-guide", help="Show 1-click harvester snippet for Google Maps profile")

    args = parser.parse_args()

    commands = {
        "build": cmd_build,
        "add": cmd_add,
        "import-takeout": cmd_import_takeout,
        "import-maps": cmd_import_maps,
        "download-images": cmd_download_images,
        "scan-inbox": cmd_scan_inbox,
        "harvest-guide": cmd_harvest_guide,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()

