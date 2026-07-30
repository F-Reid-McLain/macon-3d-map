"""3D perspective render (not flat top-down) of the downtown tile, using the
same category color scheme as render_color_map.py: tan buildings, red
hospitals, blue government, orange Mercer, grey roads, green terrain.

Rendering ALL ~24,000 buildings across the full circle in true 3D via
matplotlib isn't practical (severe depth-sorting artifacts on tall spikes,
extremely slow) -- this renders one representative tile instead.
Run from the project root: `python3 scripts/render_color_3d.py`
"""
import numpy as np
import geopandas as gpd
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from scipy.ndimage import distance_transform_edt
from scipy.interpolate import RegularGridInterpolator
from shapely.geometry import Polygon, Point, box
from shapely.geometry.base import BaseMultipartGeometry
from pyproj import Transformer
import rioxarray

CENTER_LON, CENTER_LAT = -83.625, 32.833
RADIUS_M = 5614.34
TILE_SIZE_M = 3000.0
MM_PER_M = 0.08
BASE_THICKNESS_MM = 1.2
METERS_TO_MM = 0.3
TERRAIN_MM_PER_M = MM_PER_M * 2.5
DEM_SAMPLE_SPACING_M = 20.0

TILE_I, TILE_J = 0, 0  # downtown

COLORS = {
    "hospital": "#d62728",
    "government": "#1f4e9c",
    "mercer": "#f28c28",
    "building_default": "#d2b48c",
    "road": "#6e6e6e",
}


def categorize(btype):
    if btype == "hospital":
        return "hospital"
    if btype in ("government", "public"):
        return "government"
    if btype in ("university", "dormitory"):
        return "mercer"
    return "building_default"


UTM_CRS = "EPSG:32617"
to_utm = Transformer.from_crs("EPSG:4326", UTM_CRS, always_xy=True)
CX, CY = to_utm.transform(CENTER_LON, CENTER_LAT)
CIRCLE = Point(CX, CY).buffer(RADIUS_M, quad_segs=128)

dem = rioxarray.open_rasterio("data/dem_10m.tif").squeeze()
arr = dem.values.astype(float)
mask = np.isnan(arr)
if mask.any():
    idx = distance_transform_edt(mask, return_distances=False, return_indices=True)
    arr = arr[tuple(idx)]
xs, ys = dem.x.values, dem.y.values
if ys[0] > ys[-1]:
    ys, arr = ys[::-1], arr[::-1, :]
ELEV_MIN = float(arr.min())
terrain_interp = RegularGridInterpolator((ys, xs), arr, bounds_error=False, fill_value=None)


def elevation_at(x, y):
    return float(terrain_interp((y, x)))


tx, ty = CX + TILE_I * TILE_SIZE_M, CY + TILE_J * TILE_SIZE_M
square = box(tx - TILE_SIZE_M / 2, ty - TILE_SIZE_M / 2, tx + TILE_SIZE_M / 2, ty + TILE_SIZE_M / 2)
clip = square.intersection(CIRCLE)
ox, oy = clip.centroid.x, clip.centroid.y

minx, miny, maxx, maxy = clip.bounds
nx = int(np.ceil((maxx - minx) / DEM_SAMPLE_SPACING_M)) + 1
ny = int(np.ceil((maxy - miny) / DEM_SAMPLE_SPACING_M)) + 1
xs_q = np.linspace(minx, maxx, nx)
ys_q = np.linspace(miny, maxy, ny)
X, Y = np.meshgrid(xs_q, ys_q)
elev = terrain_interp(np.column_stack([Y.ravel(), X.ravel()])).reshape(X.shape)
Z = BASE_THICKNESS_MM + (elev - ELEV_MIN) * TERRAIN_MM_PER_M
Xm = (X - ox) * MM_PER_M
Ym = (Y - oy) * MM_PER_M

fig = plt.figure(figsize=(16, 16))
ax = fig.add_subplot(111, projection="3d")

# Build terrain quads + colors as plain lists -- these get combined into ONE
# Poly3DCollection together with the building faces below, so matplotlib's
# internal per-collection depth sort can actually interleave them correctly.
# (Separate artists -- e.g. plot_surface + add_collection3d calls -- do NOT
# get cross-sorted in mplot3d, which is why the first attempt at this render
# showed the terrain incorrectly occluding almost every building.)
all_polys = []
all_colors = []

cmap = plt.get_cmap("Greens_r")
zmin_t, zmax_t = Z.min(), Z.max()
for i in range(Z.shape[0] - 1):
    for j in range(Z.shape[1] - 1):
        quad = [
            (Xm[i, j], Ym[i, j], Z[i, j]),
            (Xm[i, j + 1], Ym[i, j + 1], Z[i, j + 1]),
            (Xm[i + 1, j + 1], Ym[i + 1, j + 1], Z[i + 1, j + 1]),
            (Xm[i + 1, j], Ym[i + 1, j], Z[i + 1, j]),
        ]
        avg_z = (Z[i, j] + Z[i, j + 1] + Z[i + 1, j + 1] + Z[i + 1, j]) / 4
        t = (avg_z - zmin_t) / max(zmax_t - zmin_t, 1e-6)
        all_polys.append(quad)
        all_colors.append(cmap(0.15 + 0.6 * t))

buildings = gpd.read_file("data/buildings_hybrid_zoned.geojson").to_crs(UTM_CRS)
buildings = buildings[buildings.intersects(clip)].copy()
buildings["geometry"] = buildings["geometry"].intersection(clip)
buildings = buildings[~buildings["geometry"].is_empty]
buildings["category"] = buildings["btype"].apply(categorize)
print("buildings in downtown tile:", len(buildings))
print(buildings["category"].value_counts())

for _, row in buildings.iterrows():
    geom = row["geometry"]
    polys = geom.geoms if isinstance(geom, BaseMultipartGeometry) else [geom]
    tz = BASE_THICKNESS_MM + (elevation_at(row["geometry"].centroid.x, row["geometry"].centroid.y) - ELEV_MIN) * TERRAIN_MM_PER_M
    h_mm = max(row["height_m"] * METERS_TO_MM, 1.0)
    top_z = tz + h_mm
    color = COLORS[row["category"]]
    for poly in polys:
        if not isinstance(poly, Polygon) or poly.area <= 0:
            continue
        xs_p, ys_p = poly.exterior.xy
        xs_p = (np.array(xs_p) - ox) * MM_PER_M
        ys_p = (np.array(ys_p) - oy) * MM_PER_M
        all_polys.append(list(zip(xs_p, ys_p, [top_z] * len(xs_p))))
        all_colors.append(color)
        n = len(xs_p)
        for k in range(n - 1):
            all_polys.append([
                (xs_p[k], ys_p[k], tz), (xs_p[k + 1], ys_p[k + 1], tz),
                (xs_p[k + 1], ys_p[k + 1], top_z), (xs_p[k], ys_p[k], top_z),
            ])
            all_colors.append(color)

print(f"total combined polygons: {len(all_polys)}")
collection = Poly3DCollection(all_polys, facecolor=all_colors, edgecolor="none", linewidths=0)
ax.add_collection3d(collection)

minx_l, maxx_l = Xm.min(), Xm.max()
miny_l, maxy_l = Ym.min(), Ym.max()
ax.set_xlim(minx_l, maxx_l)
ax.set_ylim(miny_l, maxy_l)
ax.set_zlim(0, Z.max() + 10)
ax.set_box_aspect((maxx_l - minx_l, maxy_l - miny_l, (Z.max() + 10)))
ax.view_init(elev=45, azim=-60)
ax.set_axis_off()
ax.set_title("Downtown Macon 3D Map -- downtown tile, color rendering (3D perspective)", fontsize=15)

import matplotlib.patches as mpatches
legend_items = [
    mpatches.Patch(color=COLORS["building_default"], label="Buildings (general)"),
    mpatches.Patch(color=COLORS["hospital"], label="Hospitals"),
    mpatches.Patch(color=COLORS["government"], label="Government / public"),
    mpatches.Patch(color=COLORS["mercer"], label="Mercer University"),
]
ax.legend(handles=legend_items, loc="upper left", fontsize=11)

fig.tight_layout()
fig.savefig("previews/color_map_3d_downtown.png", dpi=140, facecolor="white")
print("saved previews/color_map_3d_downtown.png")
