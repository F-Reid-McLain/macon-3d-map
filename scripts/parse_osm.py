"""Parse the raw Overpass JSON into buildings / roads / water GeoDataFrames.

Run from the project root: `python3 scripts/parse_osm.py`
"""
import json
import re
import geopandas as gpd
from shapely.geometry import Polygon, LineString, mapping
from shapely.ops import unary_union

DEFAULT_LEVEL_HEIGHT_M = 3.5
DEFAULT_HEIGHT_BY_TYPE = {
    "house": 4.5, "detached": 4.5, "residential": 4.5, "bungalow": 4.5,
    "apartments": 12.0, "dormitory": 12.0,
    "commercial": 8.0, "retail": 8.0, "office": 8.0, "government": 8.0,
    "public": 8.0, "school": 8.0, "university": 8.0, "hospital": 8.0,
    "industrial": 8.0, "manufacture": 8.0, "service": 8.0,
    "church": 10.0,
    "roof": 3.0, "grandstand": 3.0, "shed": 3.0, "garage": 3.0,
}
DEFAULT_HEIGHT_FALLBACK = 7.0  # "yes"/untyped -- the overwhelming majority of buildings here
# "All roads" -- every vehicular OSM highway class, not just the major tiers.
# Excludes purely pedestrian/cycle infrastructure (footway, cycleway, path,
# steps, pedestrian, etc.) which fetch_osm.py's query already filters out.
ROAD_CLASSES = {
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "residential", "unclassified", "living_street", "service", "road", "track",
    "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link",
}

with open("data/osm_raw.json") as f:
    raw = json.load(f)

nodes = {}
ways = {}
relations = []
for el in raw["elements"]:
    if el["type"] == "node":
        nodes[el["id"]] = (el["lon"], el["lat"])
    elif el["type"] == "way":
        ways[el["id"]] = el
    elif el["type"] == "relation":
        relations.append(el)

print(f"nodes={len(nodes)} ways={len(ways)} relations={len(relations)}")


def way_coords(way):
    return [nodes[n] for n in way["nodes"] if n in nodes]


def parse_height(tags):
    for key in ("height", "building:height"):
        if key in tags:
            m = re.match(r"[\d.]+", tags[key].strip())
            if m:
                return float(m.group()), "tagged_height"
    for key in ("building:levels", "levels"):
        if key in tags:
            m = re.match(r"[\d.]+", tags[key].strip())
            if m:
                return float(m.group()) * DEFAULT_LEVEL_HEIGHT_M, "tagged_levels"
    btype = tags.get("building", "yes")
    return DEFAULT_HEIGHT_BY_TYPE.get(btype, DEFAULT_HEIGHT_FALLBACK), "default_by_type"


# ---- buildings (from ways) ----
building_rows = []
for wid, way in ways.items():
    tags = way.get("tags", {})
    if "building" not in tags:
        continue
    coords = way_coords(way)
    if len(coords) < 4 or coords[0] != coords[-1]:
        continue
    poly = Polygon(coords)
    if not poly.is_valid or poly.area <= 0:
        continue
    height_m, height_src = parse_height(tags)
    building_rows.append({
        "id": wid, "height_m": height_m, "height_src": height_src,
        "btype": tags.get("building", "yes"),
        "name": tags.get("name", ""), "geometry": poly,
    })

# ---- buildings (from multipolygon relations) ----
for rel in relations:
    tags = rel.get("tags", {})
    if "building" not in tags:
        continue
    outer_coords = []
    for member in rel.get("members", []):
        if member.get("role") == "outer" and member["type"] == "way":
            way = ways.get(member["ref"])
            if way:
                c = way_coords(way)
                if len(c) >= 4:
                    outer_coords.append(c)
    for c in outer_coords:
        if c[0] != c[-1]:
            c = c + [c[0]]
        poly = Polygon(c)
        if poly.is_valid and poly.area > 0:
            height_m, height_src = parse_height(tags)
            building_rows.append({
                "id": rel["id"], "height_m": height_m, "height_src": height_src,
                "btype": tags.get("building", "yes"),
                "name": tags.get("name", ""), "geometry": poly,
            })

buildings = gpd.GeoDataFrame(building_rows, crs="EPSG:4326")
print(f"buildings: {len(buildings)}")

# ---- roads ----
road_rows = []
for wid, way in ways.items():
    tags = way.get("tags", {})
    hw = tags.get("highway")
    if hw not in ROAD_CLASSES:
        continue
    coords = way_coords(way)
    if len(coords) < 2:
        continue
    road_rows.append({"id": wid, "class": hw, "name": tags.get("name", ""),
                       "ref": tags.get("ref", ""), "geometry": LineString(coords)})
roads = gpd.GeoDataFrame(road_rows, crs="EPSG:4326")
print(f"roads: {len(roads)}")

# ---- water (rivers as lines, natural=water as ways/relations -> polygons) ----
# `name` is kept (previously dropped entirely) so build_labels.py can label
# real named water features (the Ocmulgee River, named creeks, the lake) --
# an existing consumer (build_grid.py's water_all) only reads `kind`/
# `geometry`, so this extra column is a safe, backward-compatible addition.
water_polys = []
for wid, way in ways.items():
    tags = way.get("tags", {})
    coords = way_coords(way)
    if tags.get("natural") == "water" and len(coords) >= 4 and coords[0] == coords[-1]:
        poly = Polygon(coords)
        if poly.is_valid and poly.area > 0:
            water_polys.append((poly, tags.get("name", "")))

for rel in relations:
    tags = rel.get("tags", {})
    if tags.get("natural") != "water":
        continue
    for member in rel.get("members", []):
        if member.get("role") == "outer" and member["type"] == "way":
            way = ways.get(member["ref"])
            if way:
                c = way_coords(way)
                if len(c) >= 4:
                    if c[0] != c[-1]:
                        c = c + [c[0]]
                    poly = Polygon(c)
                    if poly.is_valid and poly.area > 0:
                        water_polys.append((poly, tags.get("name", "")))

water_lines = []
for wid, way in ways.items():
    tags = way.get("tags", {})
    if tags.get("waterway") == "river":
        coords = way_coords(way)
        if len(coords) >= 2:
            water_lines.append((LineString(coords), tags.get("name", "")))

water = gpd.GeoDataFrame(
    [{"kind": "area", "name": n, "geometry": p} for p, n in water_polys] +
    [{"kind": "line", "name": n, "geometry": l} for l, n in water_lines],
    crs="EPSG:4326",
)
print(f"water features: {len(water)} ({len(water_polys)} polygons, {len(water_lines)} river lines)")

# ---- aeroway (runways/taxiways/aprons) -- real pavement geometry, not just
# the hangar buildings (those already come through as ordinary `building`
# ways above). Runways are mapped inconsistently in OSM: some as a real
# closed-ring polygon (its actual paved width), most as a bare centerline
# with no width info at all -- kept as two different `kind`s ("runway_area"
# vs "runway_line") so the consumer can drape the polygon directly but buffer
# the line by a real assumed width. Taxiways/taxilanes are essentially always
# centerlines. Aprons (where aircraft actually park -- the closest real
# equivalent to a "parking lot" at an airport) are real closed-ring polygons.
aeroway_rows = []
for wid, way in ways.items():
    tags = way.get("tags", {})
    aw = tags.get("aeroway")
    if aw not in ("runway", "taxiway", "taxilane", "apron"):
        continue
    coords = way_coords(way)
    if len(coords) < 2:
        continue
    is_closed = len(coords) >= 4 and coords[0] == coords[-1]
    if aw == "runway":
        kind = "runway_area" if is_closed else "runway_line"
    elif aw == "apron":
        if not is_closed:
            continue
        kind = "apron"
    else:
        kind = "taxiway"
    geom = Polygon(coords) if kind in ("runway_area", "apron") else LineString(coords)
    if geom.is_empty or (kind in ("runway_area", "apron") and (not geom.is_valid or geom.area <= 0)):
        continue
    aeroway_rows.append({"id": wid, "kind": kind, "ref": tags.get("ref", ""), "geometry": geom})

aeroway = gpd.GeoDataFrame(aeroway_rows, crs="EPSG:4326")
print(f"aeroway features: {len(aeroway)}")

buildings.to_file("data/buildings_raw.geojson", driver="GeoJSON")
roads.to_file("data/roads_raw.geojson", driver="GeoJSON")
water.to_file("data/water_raw.geojson", driver="GeoJSON")
if len(aeroway):
    aeroway.to_file("data/aeroway_raw.geojson", driver="GeoJSON")

# ---- parking lots (surface lots only -- multi-storey/structured parking
# decks are already tagged `building` and captured as building volumes above,
# so skip those here to avoid representing the same real-world structure twice) ----
parking_rows = []
for wid, way in ways.items():
    tags = way.get("tags", {})
    if tags.get("amenity") != "parking" or "building" in tags:
        continue
    coords = way_coords(way)
    if len(coords) < 4 or coords[0] != coords[-1]:
        continue
    poly = Polygon(coords)
    if not poly.is_valid or poly.area <= 0:
        continue
    parking_rows.append({"id": wid, "parking_type": tags.get("parking", "surface"),
                          "name": tags.get("name", ""), "geometry": poly})

for rel in relations:
    tags = rel.get("tags", {})
    if tags.get("amenity") != "parking" or "building" in tags:
        continue
    for member in rel.get("members", []):
        if member.get("role") == "outer" and member["type"] == "way":
            way = ways.get(member["ref"])
            if way:
                c = way_coords(way)
                if len(c) >= 4:
                    if c[0] != c[-1]:
                        c = c + [c[0]]
                    poly = Polygon(c)
                    if poly.is_valid and poly.area > 0:
                        parking_rows.append({"id": rel["id"], "parking_type": tags.get("parking", "surface"),
                                              "name": tags.get("name", ""), "geometry": poly})

parking = gpd.GeoDataFrame(parking_rows, crs="EPSG:4326")
print(f"parking lots: {len(parking)}")
parking.to_file("data/parking_raw.geojson", driver="GeoJSON")

print("done")
