"""Turn data/places_raw.json (fetch_places.py's OSM output) into
output/labels.json: floating map labels for neighborhoods, hamlets, and
industrial areas, in the same local model-space coordinates as everything
else (see build_grid.py's CX/CY/MM_PER_M -- reused here via `import
build_grid as bg`, same pattern build_colored_disk.py already uses).

Each place is one OSM node (place=neighbourhood/hamlet/village/...) or way
center (landuse=industrial, named). Grouped into three display tiers so the
viewer can fade labels in by camera distance instead of showing all ~200 at
once -- see site/template.html's PLACE_LABEL_TIERS:
  - "industrial": named industrial/commercial facilities -- few, visible from
    far away.
  - "neighbourhood": named residential subdivisions -- the biggest group,
    visible at medium range.
  - "hamlet": smaller/rural named communities (OSM's hamlet/village tags) --
    visible only up close, to avoid cluttering the county-wide view.

Run from the project root, after fetch_places.py:
`python3 scripts/build_labels.py`
"""
import json

from shapely.geometry import Point

import build_grid as bg

TIER_BY_PLACE_TAG = {
    "neighbourhood": "neighbourhood",
    "suburb": "neighbourhood",
    "quarter": "neighbourhood",
    "town": "neighbourhood",
    "hamlet": "hamlet",
    "village": "hamlet",
}

# OSM node placement for a "place" point isn't always dead-center of the
# named area, and industrial way centers can sit right at a facility's edge
# -- buffer the county polygon a bit rather than doing an exact contains()
# check, so legitimate edge-of-county places aren't dropped.
COUNTY_SHAPE_LOOSE = bg.COUNTY_SHAPE.buffer(300.0)

LABEL_FLOAT_MM = 4.0  # hover text just above terrain/rooftops, avoid z-fighting


def load_places():
    with open("data/places_raw.json") as f:
        return json.load(f)["elements"]


def to_model_xyz(lat, lon):
    x_utm, y_utm = bg.to_utm.transform(lon, lat)
    z_mm = bg.terrain_z_mm(x_utm, y_utm) + LABEL_FLOAT_MM
    x_mm = (x_utm - bg.CX) * bg.MM_PER_M
    y_mm = (y_utm - bg.CY) * bg.MM_PER_M
    return x_utm, y_utm, x_mm, y_mm, z_mm


def build():
    elements = load_places()
    labels = []
    skipped_outside = 0
    for i, el in enumerate(elements):
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            continue

        if el["type"] == "node":
            lat, lon = el["lat"], el["lon"]
        else:
            center = el.get("center")
            if not center:
                continue
            lat, lon = center["lat"], center["lon"]

        place_tag = tags.get("place")
        if place_tag:
            tier = TIER_BY_PLACE_TAG.get(place_tag)
            if tier is None:
                continue
        elif tags.get("landuse") in ("industrial", "commercial"):
            tier = "industrial"
        else:
            continue

        x_utm, y_utm, x_mm, y_mm, z_mm = to_model_xyz(lat, lon)
        if not COUNTY_SHAPE_LOOSE.contains(Point(x_utm, y_utm)):
            skipped_outside += 1
            continue

        labels.append({
            "id": f"pl-{i}",
            "name": name,
            "tier": tier,
            "x": round(x_mm, 1),
            "y": round(y_mm, 1),
            "z": round(z_mm, 2),
        })

    print(f"{len(labels)} labels built, {skipped_outside} skipped (outside county)")
    by_tier = {}
    for lb in labels:
        by_tier[lb["tier"]] = by_tier.get(lb["tier"], 0) + 1
    print("by tier:", by_tier)
    return labels


if __name__ == "__main__":
    labels = build()
    with open("output/labels.json", "w") as f:
        json.dump(labels, f, indent=1)
    print("wrote output/labels.json")
