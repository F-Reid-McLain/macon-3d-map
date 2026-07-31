"""Export a color-coded version of the FULL 21-tile disk (terrain + roads +
water + buildings, matching the real print geometry) as one combined PLY +
GLB. Plain STL has no color support; 3MF export via trimesh doesn't reliably
preserve color in this environment (verified via round-trip test), so PLY
(most universal for viewers) and GLB (modern, well supported, verified
working) are used instead.

Road/water coloring approach: boolean-cutting grooves/recesses into the
terrain mesh doesn't preserve a "this face is a road" tag through the
operation, so roads and water are colored by SPATIAL CLASSIFICATION after
the cut -- each terrain face's centroid is tested against the same road
ribbon / water polygons used to cut it (via shapely.vectorized for speed),
and colored grey/blue accordingly. This is robust regardless of how the
boolean operation restructured the mesh topology.

Color scheme: tan general buildings, red hospitals, blue government/public,
orange Mercer University, greyish roads, lavender-grey parking lots, blue
water, green terrain.
Run from the project root: `python3 scripts/build_colored_disk.py`
"""
import os
import sys
import numpy as np
import geopandas as gpd
import trimesh
import shapely.vectorized
from shapely.geometry import Polygon, box
from shapely.affinity import affine_transform
from shapely.geometry.base import BaseMultipartGeometry
from shapely.ops import unary_union

sys.path.insert(0, "scripts")
import build_grid as bg  # reuse the real tile geometry/terrain/building logic

COLORS = {
    "hospital": [214, 39, 40, 255],
    "government": [31, 78, 156, 255],
    "mercer": [242, 140, 40, 255],
    "building_default": [210, 180, 140, 255],
    "terrain": [90, 160, 90, 255],
    "road": [120, 120, 120, 255],
    "parking": [150, 144, 167, 255],
    "water": [70, 120, 200, 255],
    "landmark": [184, 147, 74, 255],
}

parking_all = None
if os.path.exists("data/parking_raw.geojson"):
    parking_all = gpd.read_file("data/parking_raw.geojson").to_crs(bg.UTM_CRS)

# named buildings that also get a hotspot in site/assemble.py's "landmark"
# category -- colored brass to match that hotspot/legend color, instead of
# blending into the generic tan of every other unremarkable building.
LANDMARK_BUILDING_NAMES = {
    "Fickling & Company Building",
    "Godsey Science Center",
    "Walker-Shinholser-Rushin House",
    "Macon-Bibb Chamber of Commerce",
}


def categorize(btype):
    if btype == "hospital":
        return "hospital"
    if btype in ("government", "public"):
        return "government"
    if btype in ("university", "dormitory"):
        return "mercer"
    return "building_default"


def build_colored_tile(tile_name, clip_shape_m):
    b = bg.buildings_all[bg.buildings_all.intersects(clip_shape_m)].copy()
    b["geometry"] = b["geometry"].intersection(clip_shape_m)
    b = b[~b["geometry"].is_empty]
    b["category"] = b["btype"].apply(categorize)
    b.loc[b["name"].isin(LANDMARK_BUILDING_NAMES), "category"] = "landmark"

    r = bg.roads_all[bg.roads_all.intersects(clip_shape_m)].copy()
    r["geometry"] = r["geometry"].intersection(clip_shape_m)
    r = r[~r["geometry"].is_empty]

    wat = bg.water_all[bg.water_all.intersects(clip_shape_m)].copy()
    wat["geometry"] = wat["geometry"].intersection(clip_shape_m)
    wat = wat[~wat["geometry"].is_empty]

    if parking_all is not None:
        pk = parking_all[parking_all.intersects(clip_shape_m)].copy()
        pk["geometry"] = pk["geometry"].intersection(clip_shape_m)
        pk = pk[~pk["geometry"].is_empty]
    else:
        pk = parking_all

    if len(b) == 0 and len(r) == 0 and (pk is None or len(pk) == 0):
        return None

    plate_clip_m = clip_shape_m.buffer(bg.PLATE_MARGIN_M)
    plate_mesh, (ox, oy) = bg.build_terrain_base(plate_clip_m)
    xf = lambda g: affine_transform(g, [bg.MM_PER_M, 0, 0, bg.MM_PER_M, -ox * bg.MM_PER_M, -oy * bg.MM_PER_M])

    # ---- build road ribbon in local mm coords, for COLOR CLASSIFICATION ONLY
    # -- unlike the physical print pipeline (build_grid.py), this web-only
    # model isn't printed, so roads are NOT grooved/cut into the terrain here;
    # they render flush with the surrounding surface, just colored grey via
    # the spatial-classification pass below. Water keeps its physical recess
    # (still cut, via cut_shapes) since that reads better visually either way. ----
    #
    # Width is NOT bg.ROAD_GROOVE_WIDTH_MM (0.9mm, half-width 0.45mm) -- that's
    # sized for a physical print groove, not for this face-centroid color
    # classification. Classification tests each terrain triangle's CENTROID
    # against the ribbon (see face_colors below), and the terrain grid itself
    # has ~20m cells (bg.DEM_SAMPLE_SPACING_M) -> ~1.6mm at this 1:12,500
    # scale -- a ribbon narrower than a terrain cell mostly threads between
    # centroids without ever containing one, so roads came out as sparse,
    # broken flecks instead of a continuous line (confirmed visually before
    # this fix). ROAD_PAINT_WIDTH_MM is comfortably wider than a terrain
    # cell's ~2.3mm diagonal so a road can't cross a cell without catching its
    # centroid, while still reading as a reasonably narrow line at this scale
    # (water lines already use a visually-similar 3mm width and look fine).
    ROAD_PAINT_WIDTH_MM = 3.0
    road_ribbon_parts = []
    cut_shapes = []
    for line_utm in r["geometry"]:
        if line_utm.is_empty or line_utm.length == 0:
            continue
        line_local = xf(line_utm)
        ribbon = line_local.buffer(ROAD_PAINT_WIDTH_MM / 2)
        road_ribbon_parts.append(ribbon)
    road_ribbon = unary_union(road_ribbon_parts) if road_ribbon_parts else None

    water_shape_parts = []
    for _, row in wat.iterrows():
        geom_utm = row["geometry"]
        tz = bg.terrain_z_mm(geom_utm.centroid.x, geom_utm.centroid.y) if not geom_utm.is_empty else bg.BASE_THICKNESS_MM
        geom_local = xf(geom_utm)
        if row["kind"] == "line":
            geom_local = geom_local.buffer(3.0)
        if geom_local.is_empty:
            continue
        water_shape_parts.append(geom_local)
        parts = geom_local.geoms if isinstance(geom_local, BaseMultipartGeometry) else [geom_local]
        for part in parts:
            if part.is_empty or part.area <= 0:
                continue
            prism = trimesh.creation.extrude_polygon(part, height=bg.WATER_RECESS_MM + 1.0, engine="earcut")
            prism.apply_translation([0, 0, tz - bg.WATER_RECESS_MM])
            if prism.is_volume:
                cut_shapes.append(prism)
    water_shape = unary_union(water_shape_parts) if water_shape_parts else None

    # parking lots: flush pavement at grade (no groove cut, unlike roads/water)
    # -- just a separate spatial classification tag so they read as a distinct
    # surface from roads instead of blending into the grey road ribbons.
    parking_shape_parts = []
    if pk is not None and len(pk):
        for geom_utm in pk["geometry"]:
            geom_local = xf(geom_utm)
            if geom_local.is_empty:
                continue
            parking_shape_parts.append(geom_local)
    parking_shape = unary_union(parking_shape_parts) if parking_shape_parts else None

    if cut_shapes and plate_mesh.is_volume:
        plate_mesh.merge_vertices()
        good = []
        for c in cut_shapes:
            c.merge_vertices()
            if c.is_volume:
                good.append(c)
        if good:
            try:
                plate_mesh = trimesh.boolean.difference([plate_mesh] + good, engine="manifold")
            except Exception as e:
                print(f"  [{tile_name}] road/water cut failed, terrain stays uncut: {e}")

    # ---- spatial classification for face color (robust to boolean topology changes) ----
    face_colors = np.tile(COLORS["terrain"], (len(plate_mesh.faces), 1)).astype(np.uint8)
    centers = plate_mesh.triangles_center
    if parking_shape is not None and not parking_shape.is_empty:
        mask = shapely.vectorized.contains(parking_shape, centers[:, 0], centers[:, 1])
        face_colors[mask] = COLORS["parking"]
    if road_ribbon is not None and not road_ribbon.is_empty:
        mask = shapely.vectorized.contains(road_ribbon, centers[:, 0], centers[:, 1])
        face_colors[mask] = COLORS["road"]
    if water_shape is not None and not water_shape.is_empty:
        mask = shapely.vectorized.contains(water_shape, centers[:, 0], centers[:, 1])
        face_colors[mask] = COLORS["water"]
    plate_mesh.visual.face_colors = face_colors

    building_meshes = []
    for _, row in b.iterrows():
        geom_utm = row["geometry"]
        tz = bg.terrain_z_mm(geom_utm.centroid.x, geom_utm.centroid.y)
        geom = xf(geom_utm)
        polys = geom.geoms if isinstance(geom, BaseMultipartGeometry) else [geom]
        h_mm = max(row["height_m"] * bg.METERS_TO_MM, bg.MIN_BUILDING_HEIGHT_MM)
        color = COLORS[row["category"]]
        for poly in polys:
            if not isinstance(poly, Polygon) or poly.area <= 0 or not poly.is_valid:
                continue
            poly = Polygon(poly.exterior)
            try:
                m = trimesh.creation.extrude_polygon(poly, height=h_mm, engine="earcut")
            except Exception:
                continue
            m.apply_translation([0, 0, tz])
            m.visual.face_colors = color
            building_meshes.append(m)

    tile_mesh = trimesh.util.concatenate([plate_mesh] + building_meshes)
    # translate to the tile's TRUE global position (matches build_assembly.py)
    global_ox, global_oy = (ox - bg.CX) * bg.MM_PER_M, (oy - bg.CY) * bg.MM_PER_M
    tile_mesh.apply_translation([global_ox, global_oy, 0])
    return tile_mesh


if __name__ == "__main__":
    import os
    os.makedirs("output/colored", exist_ok=True)
    all_meshes = []
    for tname, clipped in bg.tiles:
        print(f"building {tname} ...")
        m = build_colored_tile(tname, clipped)
        if m is not None:
            all_meshes.append(m)
            print(f"  -> {len(m.faces)} faces")
        else:
            print("  -> empty, skipped")

    print(f"\nconcatenating {len(all_meshes)} tiles ...")
    full_disk = trimesh.util.concatenate(all_meshes)
    print(f"full disk: {len(full_disk.faces)} faces, bounds={full_disk.bounds.tolist()}")

    full_disk.export("output/colored/full_disk_colored.ply")
    full_disk.export("output/colored/full_disk_colored.glb")
    print("wrote output/colored/full_disk_colored.ply")
    print("wrote output/colored/full_disk_colored.glb")
