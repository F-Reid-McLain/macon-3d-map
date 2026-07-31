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

Color scheme: red hospitals, blue government/public, orange Mercer
University, brass named landmarks -- these four take priority regardless of
zoning. Every other building is colored by its zoning parcel (see
classify_zoning() / ZONING_CATEGORY_COLORS below): burlywood residential,
amethyst commercial, slate industrial, olive agricultural, grey other/planned
development, falling back to the original flat tan only if a building has no
zoning parcel match at all (~0.4% of parcels have a blank ZONINGCODE). Plus
greyish roads, lavender-grey parking lots, blue water, green terrain.
Run from the project root: `python3 scripts/build_colored_disk.py`
"""
import os
import re
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

# Zoning-derived colors, applied ONLY to buildings that are still plain
# "building_default" after the category pass below -- hospitals/government/
# Mercer/named landmarks keep their existing distinct colors regardless of
# zoning, since those are genuinely special-purpose call-outs worth keeping
# even if e.g. a hospital happens to sit on commercially-zoned land. This
# turns the ~90%+ of buildings that were previously flat tan into a real
# residential/commercial/industrial/agricultural breakdown instead of
# replacing the existing category coloring outright.
ZONING_CATEGORY_COLORS = {
    "residential": [222, 184, 135, 255],
    "commercial": [155, 89, 182, 255],
    "industrial": [127, 140, 141, 255],
    "agricultural": [154, 165, 76, 255],
    "other": [190, 190, 190, 255],
}


def classify_zoning(code):
    """Bibb County ZONINGCODE -> a simplified category, or None if blank/
    unrecognized (falls back to the plain building_default tan). Reference:
    R-1/R-1A/R-1AA/R-1AAA/R-1AAAA/R-2/R-2A/R-3/RR/HR-1/HR-2/HR-3/MHR =
    residential (density tiers + historic + manufactured-home residential);
    C-1..C-5/CBD-1/CBD-2/HC/SC = commercial; M-1/M-2/M-3 = industrial;
    A/AG = agricultural; PDC/PDR/PDI = planned-development commercial/
    residential/industrial (real, common codes, not edge cases); PDE
    ("planned development employment", going by context) and HPD/HPD-BH
    (historic preservation district, an overlay on a base zone, not a use by
    itself) are genuinely ambiguous -> "other" rather than a guess. Split-
    zoned parcels ("A/C-2", "C-1,R1A") are classified by whichever code is
    listed first -- a simplification, not a claim that only part of the
    parcel matters."""
    if not code:
        return None
    code = str(code).strip().upper()
    if not code:
        return None
    primary = re.split(r"[/,]", code)[0].strip()
    if primary in ("A", "AG"):
        return "agricultural"
    if primary.startswith("R") or primary.startswith("HR") or primary == "MHR":
        return "residential"
    if primary == "PDC":
        return "commercial"
    if primary == "PDR":
        return "residential"
    if primary == "PDI":
        return "industrial"
    if primary == "PDE" or primary.startswith("HPD"):
        return "other"
    if primary.startswith("C") or primary in ("HC", "SC"):
        return "commercial"
    if primary.startswith("M"):
        return "industrial"
    return None  # blank, or data-entry junk like '106'/'31206'


parking_all = None
if os.path.exists("data/parking_raw.geojson"):
    parking_all = gpd.read_file("data/parking_raw.geojson").to_crs(bg.UTM_CRS)

zoning_all = None
if os.path.exists("data/parcels_zoning.geojson"):
    zoning_all = gpd.read_file("data/parcels_zoning.geojson").to_crs(bg.UTM_CRS)
    zoning_all["geometry"] = zoning_all["geometry"].buffer(0)  # fix any invalid parcel rings
    zoning_all["zoning_cat"] = zoning_all["ZONINGCODE"].apply(classify_zoning)
    n_classified = zoning_all["zoning_cat"].notna().sum()
    print(f"loaded {len(zoning_all)} zoning parcels, {n_classified} classified "
          f"({100 * n_classified / len(zoning_all):.1f}%)")

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

    b["zoning_cat"] = None
    if zoning_all is not None and len(b):
        # reset_index(drop=True) on BOTH sides is load-bearing, not cosmetic: b and
        # zoning_all each keep their original row indices from the full county-wide
        # dataframes after the .intersects() filter above, which routinely collide
        # (e.g. both have a row "42"). gpd.sjoin doesn't fully guard against that --
        # confirmed by debugging a real tile where match rate silently dropped from
        # ~99% to ~6% with colliding indices, no error, just wrong results joined
        # back onto the wrong buildings. Using an explicit "b_idx" position column
        # (not pandas index alignment) to map results back removes the ambiguity
        # entirely instead of trusting index alignment a second time.
        zn = zoning_all[zoning_all.intersects(clip_shape_m)][["geometry", "zoning_cat"]].reset_index(drop=True)
        if len(zn):
            b_reset = b.reset_index(drop=True)
            b_pts = gpd.GeoDataFrame({"b_idx": b_reset.index}, geometry=b_reset.geometry.centroid,
                                      crs=bg.UTM_CRS)
            joined = gpd.sjoin(b_pts, zn, predicate="within", how="left")
            # a centroid can land inside >1 overlapping/sliver parcel; keep one match per building
            joined = joined.drop_duplicates(subset="b_idx", keep="first")
            zoning_by_pos = joined.set_index("b_idx")["zoning_cat"].reindex(b_reset.index)
            b["zoning_cat"] = zoning_by_pos.to_numpy()

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
    # against the ribbon (see face_colors below), and the terrain grid cell
    # size (bg.DEM_SAMPLE_SPACING_M) sets a hard floor: a ribbon narrower than
    # a cell mostly threads between centroids without ever containing one, so
    # roads came out as sparse, broken flecks instead of a continuous line
    # (confirmed visually). Too wide overshoots just as visibly the other way
    # -- 3.0mm fixed the brokenness at the original 20m grid, but a since-
    # reverted experiment at a 10m grid (see build_grid.py) showed that same
    # 3.0mm was now ~2x wider than needed and read as fat/blobby (road-
    # classified face share jumped from 24% to 41% of a test tile with no
    # proportional change in real road area). Computed from
    # bg.DEM_SAMPLE_SPACING_M instead of a hardcoded constant so it can't need
    # manual retuning again if that value ever changes -- 0.15x the spacing in
    # mm empirically matched both the 20m case (3.0mm) and the 10m case
    # (1.5mm) exactly.
    ROAD_PAINT_WIDTH_MM = 0.15 * bg.DEM_SAMPLE_SPACING_M
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
        # guaranteed-visibility fallback: classification only fires when a terrain
        # triangle's CENTROID falls inside the lot, so a lot smaller than roughly a
        # terrain cell (still ~13/283 county-wide even after the 10m regrade above --
        # real parking lots range down to ~30m^2) can land entirely between centroids
        # and get zero coverage, just silently vanishing. Force-color each such lot's
        # single nearest terrain face instead of leaving it uncolored -- not a
        # geometrically exact footprint, but visible, which a blank spot never is.
        from scipy.spatial import cKDTree
        tree = cKDTree(centers[:, :2])
        n_fallback = 0
        for poly in parking_shape_parts:
            parts = poly.geoms if isinstance(poly, BaseMultipartGeometry) else [poly]
            for part in parts:
                if part.is_empty or part.area <= 0:
                    continue
                if shapely.vectorized.contains(part, centers[:, 0], centers[:, 1]).any():
                    continue
                c = part.centroid
                _, idx = tree.query([c.x, c.y])
                face_colors[idx] = COLORS["parking"]
                n_fallback += 1
        if n_fallback:
            print(f"  [{tile_name}] {n_fallback} parking lot(s) too small to hit a terrain "
                  f"centroid, force-colored via nearest-face fallback")
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
        if row["category"] == "building_default" and row["zoning_cat"] in ZONING_CATEGORY_COLORS:
            color = ZONING_CATEGORY_COLORS[row["zoning_cat"]]
        else:
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
