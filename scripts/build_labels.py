"""Turn data/places_raw.json (fetch_places.py's OSM output) into
output/labels.json: floating map labels for neighborhoods, hamlets, and
industrial areas, in the same local model-space coordinates as everything
else (see build_grid.py's CX/CY/MM_PER_M -- reused here via `import
build_grid as bg`, same pattern build_colored_disk.py already uses).

Each place is one OSM node (place=neighbourhood/hamlet/village/...) or way
center (landuse=industrial, named). A fourth tier, "highway", comes from a
different source entirely: bg.roads_all (already loaded from
data/roads_raw.geojson by build_grid.py), filtered to motorway/trunk/primary
roads with a route ref or name. Grouped into four display tiers so the
viewer can fade labels in by camera distance instead of showing them all at
once -- see site/template.html's PLACE_LABEL_TIERS:
  - "highway": named/numbered highways (I-75, US 41, ...) -- visible from
    farthest away, distinct shield-style design.
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

import geopandas as gpd
from shapely.geometry import Point, MultiLineString
from shapely.ops import unary_union, linemerge
from shapely.strtree import STRtree

import build_grid as bg

TIER_BY_PLACE_TAG = {
    "neighbourhood": "neighbourhood",
    "suburb": "neighbourhood",
    "quarter": "neighbourhood",
    "town": "neighbourhood",
    "hamlet": "hamlet",
    "village": "hamlet",
}

# Real highway ways come in dozens of short OSM segments sharing one name/ref
# -- merge them back into as-long-as-possible contiguous lines (linemerge)
# before placing labels, rather than labeling every segment. Long routes
# still get a label repeated every HIGHWAY_LABEL_SPACING_M along their
# length (like a real map's repeated route shields), and merged stubs
# shorter than HIGHWAY_MIN_SEGMENT_M are skipped as not worth labeling.
HIGHWAY_CLASSES = {"motorway", "trunk", "primary"}
HIGHWAY_LABEL_SPACING_M = 4000.0
HIGHWAY_MIN_SEGMENT_M = 800.0
HIGHWAY_MAX_LABELS_PER_PART = 6  # divided highways (separate carriageways per direction
                                  # in OSM) roughly double the naive count -- cap per merged
                                  # part rather than fine-tuning spacing further

# Named water bodies, same linemerge-and-space-out treatment as highways for
# rivers (5 raw "Ocmulgee River" segments merge into far fewer real
# contiguous lines), one label at the centroid for lakes/ponds above
# WATER_AREA_MIN_M2 -- of 79 named water features in the raw OSM data, most
# of the ones below this are small private ponds (e.g. "Kraftsman
# Association Lake", "Gibson-Cary Development Corporation Pond") not real
# geographic landmarks worth labeling.
WATER_AREA_MIN_M2 = 50000.0
WATER_LABEL_SPACING_M = 5000.0
WATER_MIN_LINE_M = 800.0
WATER_MAX_LABELS_PER_PART = 4

# OSM node placement for a "place" point isn't always dead-center of the
# named area, and industrial way centers can sit right at a facility's edge
# -- buffer the county polygon a bit rather than doing an exact contains()
# check, so legitimate edge-of-county places aren't dropped.
COUNTY_SHAPE_LOOSE = bg.COUNTY_SHAPE.buffer(300.0)

LABEL_FLOAT_MM = 4.0  # hover text just above terrain/rooftops, avoid z-fighting

# Neighbourhood/hamlet nodes have no population tag in OSM (only 1 of 202
# does), so building density around the point is the best real-data proxy
# for "is this actually a substantial named place worth labeling" -- a
# handful of named points sit in fields with zero buildings within 250m
# (likely a crossroads name or a stray/inaccurate node, either way not worth
# a label), and plenty more have only a few. Chosen by inspecting the actual
# distribution: ~15 buildings within 250m is roughly the 10th percentile
# county-wide, i.e. this drops the sparsest tenth rather than gutting the
# tier.
PLACE_DENSITY_RADIUS_M = 250.0
PLACE_MIN_BUILDINGS_NEARBY = 15
_building_centroids = bg.buildings_all.geometry.centroid.values
_building_tree = STRtree(_building_centroids)


def buildings_nearby(x_utm, y_utm):
    return len(_building_tree.query(Point(x_utm, y_utm).buffer(PLACE_DENSITY_RADIUS_M)))


# Divided highways/rivers with multiple channels are mapped in OSM as
# separate parallel ways sharing one name -- linemerge treats them as
# distinct parts, so the same route/river can get two labels only a few
# dozen meters apart, visibly stacked on top of each other at this scale.
# Collapse same-tier, same-name labels within this real-world distance down
# to one.
DEDUPE_MIN_DIST_M = 150.0


def dedupe_close_labels(labels):
    threshold_mm = DEDUPE_MIN_DIST_M * bg.MM_PER_M
    kept_by_key = {}
    out = []
    for lb in labels:
        kept = kept_by_key.setdefault((lb["tier"], lb["name"]), [])
        if any(((lb["x"] - k["x"]) ** 2 + (lb["y"] - k["y"]) ** 2) ** 0.5 < threshold_mm for k in kept):
            continue
        kept.append(lb)
        out.append(lb)
    return out


def load_places():
    with open("data/places_raw.json") as f:
        return json.load(f)["elements"]


def to_model_xyz(lat, lon):
    x_utm, y_utm = bg.to_utm.transform(lon, lat)
    return to_model_xyz_utm(x_utm, y_utm)


def to_model_xyz_utm(x_utm, y_utm):
    z_mm = bg.terrain_z_mm(x_utm, y_utm) + LABEL_FLOAT_MM
    x_mm = (x_utm - bg.CX) * bg.MM_PER_M
    y_mm = (y_utm - bg.CY) * bg.MM_PER_M
    return x_utm, y_utm, x_mm, y_mm, z_mm


def highway_label_text(row):
    # Numbered route ref only -- no fallback to the OSM `name` tag. Plenty of
    # ordinary local streets (Sardis Church Road, Mulberry Street, ...) are
    # tagged highway=primary with no ref, and giving those the same
    # shield-badge treatment as I-75/US 41 looked wrong (a residential street
    # rendered exactly like an interstate) and cluttered the tier with routes
    # nobody would call a "highway". If a road has no route number, it just
    # doesn't get a highway-tier label.
    ref = (row["ref"] or "").strip()
    if ref:
        return ref.split(";")[0].strip()
    return None


def build_highway_labels():
    roads = bg.roads_all[bg.roads_all["class"].isin(HIGHWAY_CLASSES)].copy()
    roads["label_text"] = roads.apply(highway_label_text, axis=1)
    roads = roads[roads["label_text"].notna() & (roads["label_text"] != "")]

    labels = []
    i = 0
    for label_text, group in roads.groupby("label_text"):
        union = unary_union(group.geometry.tolist())
        merged = linemerge(union) if isinstance(union, MultiLineString) else union
        parts = merged.geoms if isinstance(merged, MultiLineString) else [merged]
        for part in parts:
            if part.is_empty or part.length < HIGHWAY_MIN_SEGMENT_M:
                continue
            n_pts = min(HIGHWAY_MAX_LABELS_PER_PART, max(1, int(part.length // HIGHWAY_LABEL_SPACING_M) + 1))
            for k in range(n_pts):
                frac = (k + 0.5) / n_pts
                pt = part.interpolate(frac, normalized=True)
                if not COUNTY_SHAPE_LOOSE.contains(pt):
                    continue
                _, _, x_mm, y_mm, z_mm = to_model_xyz_utm(pt.x, pt.y)
                labels.append({
                    "id": f"hwy-{i}",
                    "name": label_text,
                    "tier": "highway",
                    "x": round(x_mm, 1),
                    "y": round(y_mm, 1),
                    "z": round(z_mm, 2),
                })
                i += 1
    return labels


def build_water_labels():
    gdf = gpd.read_file("data/water_raw.geojson").to_crs(bg.UTM_CRS)
    gdf = gdf[gdf["name"].notna() & (gdf["name"] != "")]
    labels = []
    i = 0

    lines = gdf[gdf["kind"] == "line"]
    for name, group in lines.groupby("name"):
        union = unary_union(group.geometry.tolist())
        merged = linemerge(union) if isinstance(union, MultiLineString) else union
        parts = merged.geoms if isinstance(merged, MultiLineString) else [merged]
        for part in parts:
            if part.is_empty or part.length < WATER_MIN_LINE_M:
                continue
            n_pts = min(WATER_MAX_LABELS_PER_PART, max(1, int(part.length // WATER_LABEL_SPACING_M) + 1))
            for k in range(n_pts):
                frac = (k + 0.5) / n_pts
                pt = part.interpolate(frac, normalized=True)
                if not COUNTY_SHAPE_LOOSE.contains(pt):
                    continue
                _, _, x_mm, y_mm, z_mm = to_model_xyz_utm(pt.x, pt.y)
                labels.append({"id": f"wtr-{i}", "name": name, "tier": "water",
                               "x": round(x_mm, 1), "y": round(y_mm, 1), "z": round(z_mm, 2)})
                i += 1

    # lakes/ponds: a name can span multiple disjoint polygon parts (e.g. an
    # inlet mapped separately) -- union by name first so area/centroid
    # reflect the whole named feature, not just one fragment of it.
    areas = gdf[gdf["kind"] == "area"]
    for name, group in areas.groupby("name"):
        union = unary_union(group.geometry.tolist())
        if union.area < WATER_AREA_MIN_M2:
            continue
        pt = union.centroid
        if not COUNTY_SHAPE_LOOSE.contains(pt):
            continue
        _, _, x_mm, y_mm, z_mm = to_model_xyz_utm(pt.x, pt.y)
        labels.append({"id": f"wtr-{i}", "name": name, "tier": "water",
                       "x": round(x_mm, 1), "y": round(y_mm, 1), "z": round(z_mm, 2)})
        i += 1

    return labels


def build():
    elements = load_places()
    labels = []
    skipped_outside = 0
    skipped_sparse = 0
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
        elif tags.get("landuse") in ("industrial", "commercial") and tags.get("pipeline") != "substation":
            tier = "industrial"
        else:
            continue

        x_utm, y_utm, x_mm, y_mm, z_mm = to_model_xyz(lat, lon)
        if not COUNTY_SHAPE_LOOSE.contains(Point(x_utm, y_utm)):
            skipped_outside += 1
            continue

        if tier in ("neighbourhood", "hamlet") and buildings_nearby(x_utm, y_utm) < PLACE_MIN_BUILDINGS_NEARBY:
            skipped_sparse += 1
            continue

        labels.append({
            "id": f"pl-{i}",
            "name": name,
            "tier": tier,
            "x": round(x_mm, 1),
            "y": round(y_mm, 1),
            "z": round(z_mm, 2),
        })

    print(f"{len(labels)} place labels built, {skipped_outside} skipped (outside county), "
          f"{skipped_sparse} skipped (too few buildings nearby)")

    hwy_labels = build_highway_labels()
    print(f"{len(hwy_labels)} highway labels built")
    labels += hwy_labels

    water_labels = build_water_labels()
    print(f"{len(water_labels)} water labels built")
    labels += water_labels

    before_dedupe = len(labels)
    labels = dedupe_close_labels(labels)
    print(f"{before_dedupe - len(labels)} near-duplicate labels merged (divided highways/channels)")

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
