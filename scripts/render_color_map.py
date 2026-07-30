import geopandas as gpd
import matplotlib.pyplot as plt
from shapely.geometry import Point
from pyproj import Transformer
import numpy as np

CENTER_LON, CENTER_LAT = -83.625, 32.833
RADIUS_M = 5614.34

COLORS = {
    "background": "#8fbf7f",   # green grass/ground
    "road": "#8a8a8a",         # grey roads
    "building_default": "#d2b48c",  # tan
    "hospital": "#d62728",     # red
    "government": "#1f4e9c",   # blue
    "mercer": "#f28c28",       # orange
}


def categorize(btype):
    if btype == "hospital":
        return "hospital"
    if btype in ("government", "public"):
        return "government"
    if btype in ("university", "dormitory"):
        return "mercer"
    return "building_default"


to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32617", always_xy=True)
CX, CY = to_utm.transform(CENTER_LON, CENTER_LAT)
circle = Point(CX, CY).buffer(RADIUS_M, quad_segs=128)
circle_gdf = gpd.GeoDataFrame(geometry=[circle], crs="EPSG:32617")

buildings = gpd.read_file("data/buildings_hybrid_zoned.geojson").to_crs("EPSG:32617")
buildings = buildings[buildings.intersects(circle)].copy()
buildings["geometry"] = buildings["geometry"].intersection(circle)
buildings = buildings[~buildings["geometry"].is_empty]
buildings["category"] = buildings["btype"].apply(categorize)

roads = gpd.read_file("data/roads_raw.geojson").to_crs("EPSG:32617")
roads = roads[roads.intersects(circle)].copy()
roads["geometry"] = roads["geometry"].intersection(circle)
roads = roads[~roads["geometry"].is_empty]

water = gpd.read_file("data/water_raw.geojson").to_crs("EPSG:32617")
water = water[water.intersects(circle)].copy()
water["geometry"] = water["geometry"].intersection(circle)
water = water[~water["geometry"].is_empty]

print("building categories:")
print(buildings["category"].value_counts())

fig, ax = plt.subplots(figsize=(18, 18))
circle_gdf.plot(ax=ax, color=COLORS["background"], edgecolor="none")

water_line = water[water["kind"] == "line"].copy()
water_line["geometry"] = water_line["geometry"].buffer(25)
water_poly = water[water["kind"] == "area"]
for gdf in (water_poly, water_line):
    if len(gdf):
        gdf.plot(ax=ax, color="#5f9ea0", edgecolor="none")

roads.plot(ax=ax, color=COLORS["road"], linewidth=1.0, zorder=3)

order = ["building_default", "mercer", "government", "hospital"]
for cat in order:
    sub = buildings[buildings["category"] == cat]
    if len(sub):
        sub.plot(ax=ax, color=COLORS[cat], edgecolor="black", linewidth=0.1, zorder=4)

# legend
import matplotlib.patches as mpatches
legend_items = [
    mpatches.Patch(color=COLORS["building_default"], label="Buildings (general)"),
    mpatches.Patch(color=COLORS["hospital"], label="Hospitals"),
    mpatches.Patch(color=COLORS["government"], label="Government / public"),
    mpatches.Patch(color=COLORS["mercer"], label="Mercer University"),
    mpatches.Patch(color=COLORS["road"], label="Roads"),
    mpatches.Patch(color="#5f9ea0", label="Water"),
    mpatches.Patch(color=COLORS["background"], label="Ground"),
]
ax.legend(handles=legend_items, loc="lower left", fontsize=11, framealpha=0.9)

ax.set_title("Downtown Macon 3D Map -- color rendering", fontsize=18)
ax.set_aspect("equal")
ax.set_axis_off()
fig.tight_layout()
fig.savefig("previews/color_map_rendering.png", dpi=150, facecolor="white")
print("saved previews/color_map_rendering.png")
