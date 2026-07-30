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
                       "geometry": LineString(coords)})
roads = gpd.GeoDataFrame(road_rows, crs="EPSG:4326")
print(f"roads: {len(roads)}")

# ---- water (rivers as lines, natural=water as ways/relations -> polygons) ----
water_polys = []
for wid, way in ways.items():
    tags = way.get("tags", {})
    coords = way_coords(way)
    if tags.get("natural") == "water" and len(coords) >= 4 and coords[0] == coords[-1]:
        poly = Polygon(coords)
        if poly.is_valid and poly.area > 0:
            water_polys.append(poly)

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
                        water_polys.append(poly)

water_lines = []
for wid, way in ways.items():
    tags = way.get("tags", {})
    if tags.get("waterway") == "river":
        coords = way_coords(way)
        if len(coords) >= 2:
            water_lines.append(LineString(coords))

water = gpd.GeoDataFrame(
    [{"kind": "area", "geometry": p} for p in water_polys] +
    [{"kind": "line", "geometry": l} for l in water_lines],
    crs="EPSG:4326",
)
print(f"water features: {len(water)} ({len(water_polys)} polygons, {len(water_lines)} river lines)")

buildings.to_file("data/buildings_raw.geojson", driver="GeoJSON")
roads.to_file("data/roads_raw.geojson", driver="GeoJSON")
water.to_file("data/water_raw.geojson", driver="GeoJSON")

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
