"""Build a fixed-scale grid of tiles covering the REAL Bibb County boundary
(county_boundary/bibb_county.geojson, US Census cartographic boundary
file) so all tiles share one consistent scale and can be physically
assembled into one composite city model -- unlike the earlier
downtown_core/college_hill/mercer tiles, which were each independently
auto-scaled to fill 200mm and do NOT share a scale.

Originally clipped to a circle (center + radius) inscribed inside the county
instead of the county itself -- deliberate at the time, since a circle is
the largest shape that guarantees every tile is print-bed-sized (see
TILE_SIZE_M below), and downtown was the only area anyone cared about. Now
covering the whole county, a circumscribing circle would waste ~3x the area
in neighboring counties, so tiles are clipped to the actual county polygon
instead -- same approach the sibling commuting-project repo's county models
already use. TILE_SIZE_M is kept as-is even though the print-bed constraint
that originally sized it doesn't apply to this (web, unprinted) repo -- it's
just a convenient generation-chunk size; the final model is one concatenated
mesh regardless of how many tiles it was built from.

Each tile's own plate is shaped as (its grid square) INTERSECTED WITH (the
county polygon), not a plain rectangle: tiles fully inside the county end up
as full squares, while tiles straddling the county line come out as smaller
partial/irregular pieces.

The base plate follows REAL USGS elevation data (2.5x vertically exaggerated,
confirmed against test tiles) instead of being flat -- Macon's downtown
bluff and the Ocmulgee River floodplain are both real, substantial terrain
features, not just empty space. Buildings and road/water cuts are shifted to
the local terrain height at their own centroid (an approximation -- not a
true per-vertex drape -- but reasonable at this scale/resolution).

Run from the project root: `python3 scripts/build_grid.py`
"""
import os
import numpy as np
import geopandas as gpd
import trimesh
import rioxarray
from scipy.ndimage import distance_transform_edt
from scipy.interpolate import RegularGridInterpolator
from shapely.geometry import Polygon, Point, box
from shapely.affinity import affine_transform
from shapely.geometry.base import BaseMultipartGeometry
from pyproj import Transformer

# ---- config ----
CENTER_LON, CENTER_LAT = -83.625, 32.833   # tile-grid origin only (downtown) -- doesn't
                                            # need to be the county's own centroid, tiles
                                            # just need to cover the plane and get clipped
TILE_SIZE_M = 3000.0        # 3km grid spacing (generation-chunk size, see module docstring)
MM_PER_M = 0.08             # FIXED horizontal scale for every tile: 1:12,500
BASE_THICKNESS_MM = 1.2     # min material above the terrain's own lowest point
MIN_BUILDING_HEIGHT_MM = 1.0
METERS_TO_MM = 0.3          # building height exaggeration
TERRAIN_MM_PER_M = MM_PER_M * 2.5   # confirmed via terrain test tiles: 2.5x exaggeration
ROAD_GROOVE_WIDTH_MM = 0.9
ROAD_GROOVE_DEPTH_MM = 0.3
WATER_RECESS_MM = 0.4
PLATE_MARGIN_M = 15.0
MIN_TILE_CONTENT_M2 = 2000.0
DEM_SAMPLE_SPACING_M = float(os.environ.get("DEM_SAMPLE_SPACING_M", "20.0"))
                               # tried halving this to 10m for sharper road/parking-lot color
                               # classification -- reverted. Across the WHOLE COUNTY (unlike a
                               # dense downtown test tile, which is ~44% terrain) terrain turns
                               # out to be ~78% of total geometry, so quadrupling terrain
                               # resolution roughly tripled the ENTIRE model (8.6M -> 28.7M
                               # faces, raw GLB 175MB -> 577MB) and Draco's WASM encoder hit a
                               # hard memory ceiling and aborted outright, not just ran slow.
                               # See build_colored_disk.py's parking-lot fallback for how small
                               # features got handled without needing more geometry at all.
                               # Configurable via env var (default 20.0, the desktop value) so
                               # the SAME pipeline can build a coarser "mobile" variant too --
                               # see scripts/build_mobile.sh and CLAUDE.md's memory-budget notes.
                               # Going COARSER (a bigger number) is the safe direction -- it's
                               # the opposite of the failed 10m experiment above, so this doesn't
                               # risk the Draco memory-ceiling failure that motivated reverting.

UTM_CRS = "EPSG:32617"
OUT_DIR = "output/grid"
BUILDINGS_PATH = "data/buildings_hybrid_zoned.geojson"
COUNTY_BOUNDARY_PATH = "county_boundary/bibb_county.geojson"

to_utm = Transformer.from_crs("EPSG:4326", UTM_CRS, always_xy=True)
CX, CY = to_utm.transform(CENTER_LON, CENTER_LAT)

_county_gdf = gpd.read_file(COUNTY_BOUNDARY_PATH).to_crs(UTM_CRS)
COUNTY_SHAPE = _county_gdf.geometry.iloc[0]
_cminx, _cminy, _cmaxx, _cmaxy = COUNTY_SHAPE.bounds

print(f"center (utm) = ({CX:.1f}, {CY:.1f}), county bounds (utm) = "
      f"({_cminx:.0f}, {_cminy:.0f}, {_cmaxx:.0f}, {_cmaxy:.0f}), tile={TILE_SIZE_M:.0f}m, "
      f"scale=1:{1/MM_PER_M/1000:.3f}k, terrain exaggeration={TERRAIN_MM_PER_M/MM_PER_M:.2f}x")

# ---- DEM: load, fill small gaps, build an interpolator in UTM meters ----
dem = rioxarray.open_rasterio("data/dem_10m.tif").squeeze()
_arr = dem.values.astype(float)
_mask = np.isnan(_arr)
if _mask.any():
    _idx = distance_transform_edt(_mask, return_distances=False, return_indices=True)
    _arr = _arr[tuple(_idx)]
_xs = dem.x.values
_ys = dem.y.values
if _ys[0] > _ys[-1]:
    _ys = _ys[::-1]
    _arr = _arr[::-1, :]
ELEV_MIN = float(_arr.min())
_terrain_interp = RegularGridInterpolator((_ys, _xs), _arr, bounds_error=False, fill_value=None)


def elevation_at(x, y):
    return float(_terrain_interp((y, x)))


def elevation_grid(xs_q, ys_q):
    X, Y = np.meshgrid(xs_q, ys_q)
    pts = np.column_stack([Y.ravel(), X.ravel()])
    return _terrain_interp(pts).reshape(X.shape)


def terrain_z_mm(x, y):
    return BASE_THICKNESS_MM + (elevation_at(x, y) - ELEV_MIN) * TERRAIN_MM_PER_M


def terrain_z_mm_batch(xs, ys):
    """Vectorized terrain_z_mm for arrays of UTM (x,y) -- used to drape decal
    geometry (e.g. road ribbons) per-VERTEX instead of extruding it flat at
    one sampled height, which floats/sinks relative to real terrain wherever
    the shape spans more elevation change than that one sample captured."""
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    elev = _terrain_interp(np.column_stack([ys, xs]))
    return BASE_THICKNESS_MM + (elev - ELEV_MIN) * TERRAIN_MM_PER_M


# ---- build the tile grid: keep squares whose intersection with the county is non-trivial ----
n_i = int(np.ceil(max(CX - _cminx, _cmaxx - CX) / TILE_SIZE_M)) + 1
n_j = int(np.ceil(max(CY - _cminy, _cmaxy - CY) / TILE_SIZE_M)) + 1
tiles = []
for i in range(-n_i, n_i + 1):
    for j in range(-n_j, n_j + 1):
        tx, ty = CX + i * TILE_SIZE_M, CY + j * TILE_SIZE_M
        square = box(tx - TILE_SIZE_M / 2, ty - TILE_SIZE_M / 2, tx + TILE_SIZE_M / 2, ty + TILE_SIZE_M / 2)
        clipped = square.intersection(COUNTY_SHAPE)
        if clipped.is_empty or clipped.area < MIN_TILE_CONTENT_M2:
            continue
        name = f"tile_{i:+03d}_{j:+03d}".replace("+", "p").replace("-", "m")
        tiles.append((name, clipped))

print(f"tile grid: {len(tiles)} tiles")

buildings_all = gpd.read_file(BUILDINGS_PATH).to_crs(UTM_CRS)
roads_all = gpd.read_file("data/roads_raw.geojson").to_crs(UTM_CRS)
water_all = gpd.read_file("data/water_raw.geojson").to_crs(UTM_CRS)


def build_terrain_base(clip_shape_m):
    """Heightfield mesh (rectangular grid over the tile's bounding box,
    trimmed to the real clip shape via boolean intersection). Returns
    (mesh, (ox, oy)) where (ox,oy) is the tile's local-frame origin in UTM."""
    minx, miny, maxx, maxy = clip_shape_m.bounds
    nx = max(4, int(np.ceil((maxx - minx) / DEM_SAMPLE_SPACING_M)) + 1)
    ny = max(4, int(np.ceil((maxy - miny) / DEM_SAMPLE_SPACING_M)) + 1)
    xs_q = np.linspace(minx, maxx, nx)
    ys_q = np.linspace(miny, maxy, ny)
    elev = elevation_grid(xs_q, ys_q)
    z = BASE_THICKNESS_MM + (elev - ELEV_MIN) * TERRAIN_MM_PER_M

    ox, oy = clip_shape_m.centroid.x, clip_shape_m.centroid.y
    X, Y = np.meshgrid(xs_q, ys_q)
    Xm = (X - ox) * MM_PER_M
    Ym = (Y - oy) * MM_PER_M

    verts_top = np.column_stack([Xm.ravel(), Ym.ravel(), z.ravel()])
    verts_bot = np.column_stack([Xm.ravel(), Ym.ravel(), np.zeros(z.size)])

    def vid(i, j, top):
        return (0 if top else ny * nx) + i * nx + j

    faces = []
    for i in range(ny - 1):
        for j in range(nx - 1):
            a, b, c, d = vid(i, j, True), vid(i, j + 1, True), vid(i + 1, j + 1, True), vid(i + 1, j, True)
            faces.append([a, b, c]); faces.append([a, c, d])
            a2, b2, c2, d2 = vid(i, j, False), vid(i, j + 1, False), vid(i + 1, j + 1, False), vid(i + 1, j, False)
            faces.append([a2, c2, b2]); faces.append([a2, d2, c2])

    for j in range(nx - 1):
        i = 0
        faces.append([vid(i, j, True), vid(i, j, False), vid(i, j + 1, False)])
        faces.append([vid(i, j, True), vid(i, j + 1, False), vid(i, j + 1, True)])
        i = ny - 1
        faces.append([vid(i, j, True), vid(i, j + 1, False), vid(i, j, False)])
        faces.append([vid(i, j, True), vid(i, j + 1, True), vid(i, j + 1, False)])
    for i in range(ny - 1):
        j = 0
        faces.append([vid(i, j, True), vid(i + 1, j, False), vid(i, j, False)])
        faces.append([vid(i, j, True), vid(i + 1, j, True), vid(i + 1, j, False)])
        j = nx - 1
        faces.append([vid(i, j, True), vid(i, j, False), vid(i + 1, j, False)])
        faces.append([vid(i, j, True), vid(i + 1, j, False), vid(i + 1, j, True)])

    verts = np.vstack([verts_top, verts_bot])
    mesh = trimesh.Trimesh(vertices=verts, faces=np.array(faces), process=True)
    mesh.merge_vertices()

    clip_local = affine_transform(clip_shape_m, [MM_PER_M, 0, 0, MM_PER_M, -ox * MM_PER_M, -oy * MM_PER_M])
    zmax = float(z.max()) + 5.0
    clip_parts = clip_local.geoms if isinstance(clip_local, BaseMultipartGeometry) else [clip_local]
    clip_prisms = []
    for p in clip_parts:
        if p.area <= 0:
            continue
        prism = trimesh.creation.extrude_polygon(p, height=zmax + 10, engine="earcut")
        prism.apply_translation([0, 0, -5])
        clip_prisms.append(prism)
    trimmed = trimesh.boolean.intersection([mesh] + clip_prisms, engine="manifold")
    return trimmed, (ox, oy)


def build_tile(name, clip_shape_m):
    b = buildings_all[buildings_all.intersects(clip_shape_m)].copy()
    b["geometry"] = b["geometry"].intersection(clip_shape_m)
    b = b[~b["geometry"].is_empty]
    r = roads_all[roads_all.intersects(clip_shape_m)].copy()
    r["geometry"] = r["geometry"].intersection(clip_shape_m)
    r = r[~r["geometry"].is_empty]
    wat = water_all[water_all.intersects(clip_shape_m)].copy()
    wat["geometry"] = wat["geometry"].intersection(clip_shape_m)
    wat = wat[~wat["geometry"].is_empty]

    if len(b) == 0 and len(r) == 0:
        print(f"  [{name}] empty, skipping")
        return None

    plate_clip_m = clip_shape_m.buffer(PLATE_MARGIN_M)
    plate_mesh, (ox, oy) = build_terrain_base(plate_clip_m)
    if not plate_mesh.is_volume:
        print(f"  [{name}] note: terrain base not a clean volume right after trimming "
              f"(watertight={plate_mesh.is_watertight}, winding_consistent={plate_mesh.is_winding_consistent})")
    xf = lambda g: affine_transform(g, [MM_PER_M, 0, 0, MM_PER_M, -ox * MM_PER_M, -oy * MM_PER_M])

    b_utm_geom = b["geometry"].copy()  # keep pre-transform (UTM) copies for terrain sampling
    r_utm_geom = r["geometry"].copy()
    wat_utm_geom = wat["geometry"].copy()
    b["geometry"] = b["geometry"].apply(xf)
    r["geometry"] = r["geometry"].apply(xf)
    wat["geometry"] = wat["geometry"].apply(xf)
    b["height_mm"] = b["height_m"] * METERS_TO_MM

    # engrave roads at their own local terrain height (per-line, hole-free)
    cut_shapes = []
    n_road_cuts = 0
    for line_local, line_utm in zip(r["geometry"], r_utm_geom):
        if line_local.is_empty or line_local.length == 0:
            continue
        tz = terrain_z_mm(line_utm.centroid.x, line_utm.centroid.y)
        ribbon = line_local.buffer(ROAD_GROOVE_WIDTH_MM / 2)
        parts = ribbon.geoms if isinstance(ribbon, BaseMultipartGeometry) else [ribbon]
        for part in parts:
            if part.is_empty or part.area <= 0:
                continue
            prism = trimesh.creation.extrude_polygon(part, height=ROAD_GROOVE_DEPTH_MM + 1.0, engine="earcut")
            prism.apply_translation([0, 0, tz - ROAD_GROOVE_DEPTH_MM])
            if prism.is_volume:
                cut_shapes.append(prism)
                n_road_cuts += 1

    n_water_cuts = 0
    for (_, row), geom_utm in zip(wat.iterrows(), wat_utm_geom):
        geom = row["geometry"]
        tz = terrain_z_mm(geom_utm.centroid.x, geom_utm.centroid.y) if not geom_utm.is_empty else BASE_THICKNESS_MM
        if row["kind"] == "line":
            geom = geom.buffer(3.0)
        if geom.is_empty:
            continue
        parts = geom.geoms if isinstance(geom, BaseMultipartGeometry) else [geom]
        for part in parts:
            if part.is_empty or part.area <= 0:
                continue
            prism = trimesh.creation.extrude_polygon(part, height=WATER_RECESS_MM + 1.0, engine="earcut")
            prism.apply_translation([0, 0, tz - WATER_RECESS_MM])
            if prism.is_volume:
                cut_shapes.append(prism)
                n_water_cuts += 1

    if cut_shapes:
        plate_mesh.merge_vertices()
        good_cuts = []
        for c in cut_shapes:
            c.merge_vertices()
            if c.is_volume:
                good_cuts.append(c)
        n_dropped = len(cut_shapes) - len(good_cuts)
        if n_dropped:
            print(f"  [{name}] dropped {n_dropped} non-volume cut shape(s) after merge_vertices")
        if good_cuts and plate_mesh.is_volume:
            try:
                plate_mesh = trimesh.boolean.difference([plate_mesh] + good_cuts, engine="manifold")
            except Exception as e:
                print(f"  [{name}] WARNING: road/water groove cut failed ({e}); "
                      f"keeping terrain base uncut for this tile")
        elif not plate_mesh.is_volume:
            print(f"  [{name}] WARNING: terrain base is not a clean volume; "
                  f"keeping it uncut (no road/water grooves) for this tile")

    building_meshes = []
    n_skipped = 0
    for (_, row), geom_utm in zip(b.iterrows(), b_utm_geom):
        geom = row["geometry"]
        tz = terrain_z_mm(geom_utm.centroid.x, geom_utm.centroid.y)
        polys = geom.geoms if isinstance(geom, BaseMultipartGeometry) else [geom]
        h_mm = max(row["height_mm"], MIN_BUILDING_HEIGHT_MM)
        for poly in polys:
            if not isinstance(poly, Polygon) or poly.area <= 0 or not poly.is_valid:
                n_skipped += 1
                continue
            poly = Polygon(poly.exterior)
            try:
                m = trimesh.creation.extrude_polygon(poly, height=h_mm, engine="earcut")
            except Exception:
                n_skipped += 1
                continue
            m.apply_translation([0, 0, tz])
            building_meshes.append(m)

    solid = trimesh.util.concatenate([plate_mesh] + building_meshes)
    solid.merge_vertices()

    out_path = f"{OUT_DIR}/{name}.stl"
    solid.export(out_path)
    print(f"  [{name}] buildings={len(b)} roads(cuts)={n_road_cuts} water(cuts)={n_water_cuts} "
          f"skipped={n_skipped} bounds={[round(x,1) for x in solid.bounds[1]]}")

    if len(b):
        b[["id", "name", "height_mm", "geometry"]].to_file(f"{OUT_DIR}/{name}_buildings.geojson", driver="GeoJSON")
    if len(r):
        r.to_file(f"{OUT_DIR}/{name}_roads.geojson", driver="GeoJSON")
    return solid


if __name__ == "__main__":
    built = 0
    for name, clipped_m in tiles:
        result = build_tile(name, clipped_m)
        if result is not None:
            built += 1
    print(f"\ndone: {built}/{len(tiles)} tiles built into {OUT_DIR}/")
