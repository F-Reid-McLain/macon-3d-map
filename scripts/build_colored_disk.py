"""Export a color-coded version of the full county model as ONE multi-node
GLB (a trimesh.Scene with named geometries), so each legend category can be
independently shown/hidden in the browser -- see site/template.html's legend
toggle checkboxes, which match mesh objects by these exact node names.

Buildings are naturally separable (each is its own extruded polygon before
concatenation), so they're grouped by category and concatenated per-category
instead of all together. Terrain/roads/water/parking are NOT naturally
separable this way -- they used to be colored via spatial classification of
a single continuous terrain mesh's face centroids (testing each face against
the road/water/parking polygons), which baked all four into one blob with no
way to toggle just "roads" independently. Replaced with a decal approach:
terrain is now a single uniformly-green mesh, and roads/water/parking are
each a separate thin colored prism (~0.12mm) extruded directly from their
own real polygon shape and lifted ~0.03mm above (or, for water, resting at
the bottom of its recess) the terrain surface -- clearly on top, no
z-fighting, and each one is its own node, hence toggleable. This also
incidentally eliminates the old "parking lot too small to hit a terrain
face centroid" fallback hack entirely: a decal is extruded straight from the
lot's own polygon, so there's no terrain-grid-resolution dependency to fall
short of in the first place.

Color scheme: red hospitals, blue government/public, orange Mercer
University, brass named landmarks -- these four take priority regardless of
zoning. Every other building is colored by its zoning parcel (see
classify_zoning() / ZONING_CATEGORY_COLORS below): burlywood residential,
amethyst commercial, slate industrial, olive agricultural, grey other/planned
development, falling back to the original flat tan ("unclassified") only if
a building has no zoning parcel match at all (~0.4% of parcels have a blank
ZONINGCODE). Plus greyish roads, lavender-grey parking lots, blue water,
green terrain.
Run from the project root: `python3 scripts/build_colored_disk.py`
"""
import os
import re
import sys
import numpy as np
import geopandas as gpd
import trimesh
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

# Every node name that ends up in the exported Scene, in legend order -- also
# the exact set of names site/template.html looks for when wiring up toggle
# checkboxes. "terrain" is deliberately NOT toggleable in the UI (hiding the
# ground plane isn't useful), but it's still its own node for consistency.
CATEGORIES = [
    "terrain", "water", "road", "parking",
    "hospital", "government", "mercer", "landmark",
    "residential", "commercial", "industrial", "agricultural", "other", "unclassified",
]

DECAL_HEIGHT_MM = 0.12
DECAL_LIFT_MM = 0.03  # clears the decal off the terrain surface it sits on -- avoids z-fighting


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


def effective_category(category, zoning_cat):
    """Collapses a building's (category, zoning_cat) pair down to one of
    CATEGORIES -- the node it gets concatenated into."""
    if category != "building_default":
        return category  # hospital / government / mercer / landmark
    if zoning_cat in ZONING_CATEGORY_COLORS:
        return zoning_cat  # residential / commercial / industrial / agricultural / other
    return "unclassified"


def category_color(cat):
    if cat in ZONING_CATEGORY_COLORS:
        return ZONING_CATEGORY_COLORS[cat]
    if cat == "unclassified":
        return COLORS["building_default"]
    return COLORS[cat]


def build_colored_tile(tile_name, clip_shape_m):
    """Returns {category_name: mesh} for whichever categories have any
    geometry in this tile (categories with nothing here are simply absent
    from the dict), already translated to this tile's true global position."""
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

    result = {cat: [] for cat in CATEGORIES}

    plate_clip_m = clip_shape_m.buffer(bg.PLATE_MARGIN_M)
    plate_mesh, (ox, oy) = bg.build_terrain_base(plate_clip_m)
    xf = lambda g: affine_transform(g, [bg.MM_PER_M, 0, 0, bg.MM_PER_M, -ox * bg.MM_PER_M, -oy * bg.MM_PER_M])

    # ---- roads: thin decal prisms extruded from the road network's own
    # shape (not spatial classification against terrain faces). Width is a
    # real paint-stroke width now, not tuned around terrain grid cell size
    # like the old classification approach needed.
    #
    # UNION the ribbons in UTM space FIRST, before extruding -- extruding
    # each individual road segment's ribbon separately (as a first pass did)
    # measured 1.08M faces for just 3 tiles' worth of roads, more than the
    # ENTIRE terrain mesh for the same area, because adjacent/crossing
    # streets' buffered ribbons overlap heavily at every intersection and
    # each tiny segment pays the fixed top+bottom+wall-triangle overhead of
    # its own separate extrude_polygon() call. Unioning first collapses all
    # that overlap into one clean shape (or a few disjoint clusters) and
    # extrudes each ONCE. Height is sampled per resulting disjoint cluster's
    # own centroid (not one height for the whole tile), so hilly terrain
    # still gets reasonable per-area accuracy despite the merge. ----
    ROAD_PAINT_WIDTH_MM = 3.0
    road_width_m = ROAD_PAINT_WIDTH_MM / bg.MM_PER_M
    road_ribbons_utm = [line_utm.buffer(road_width_m / 2) for line_utm in r["geometry"]
                         if not line_utm.is_empty and line_utm.length > 0]
    road_union_utm = unary_union(road_ribbons_utm) if road_ribbons_utm else None
    if road_union_utm is not None and not road_union_utm.is_empty:
        clusters = road_union_utm.geoms if isinstance(road_union_utm, BaseMultipartGeometry) else [road_union_utm]
        for cluster_utm in clusters:
            if cluster_utm.is_empty or cluster_utm.area <= 0:
                continue
            tz = bg.terrain_z_mm(cluster_utm.centroid.x, cluster_utm.centroid.y)
            part_local = xf(cluster_utm)
            try:
                decal = trimesh.creation.extrude_polygon(part_local, height=DECAL_HEIGHT_MM, engine="earcut")
            except Exception:
                continue
            decal.apply_translation([0, 0, tz + DECAL_LIFT_MM])
            decal.visual.face_colors = COLORS["road"]
            result["road"].append(decal)

    # ---- water: keep the real geometric recess cut into the terrain (a
    # genuine depression looks better than a flat decal alone), but color it
    # via a separate decal resting at the bottom of that recess instead of
    # spatial-classifying terrain faces, so it's still its own toggleable
    # node. ----
    cut_shapes = []
    for _, row in wat.iterrows():
        geom_utm = row["geometry"]
        tz = bg.terrain_z_mm(geom_utm.centroid.x, geom_utm.centroid.y) if not geom_utm.is_empty else bg.BASE_THICKNESS_MM
        geom_local = xf(geom_utm)
        if row["kind"] == "line":
            geom_local = geom_local.buffer(3.0)
        if geom_local.is_empty:
            continue
        parts = geom_local.geoms if isinstance(geom_local, BaseMultipartGeometry) else [geom_local]
        for part in parts:
            if part.is_empty or part.area <= 0:
                continue
            try:
                cut_prism = trimesh.creation.extrude_polygon(part, height=bg.WATER_RECESS_MM + 1.0, engine="earcut")
            except Exception:
                continue
            cut_prism.apply_translation([0, 0, tz - bg.WATER_RECESS_MM])
            if cut_prism.is_volume:
                cut_shapes.append(cut_prism)
            try:
                decal = trimesh.creation.extrude_polygon(part, height=DECAL_HEIGHT_MM, engine="earcut")
            except Exception:
                continue
            decal.apply_translation([0, 0, tz - bg.WATER_RECESS_MM + DECAL_LIFT_MM])
            decal.visual.face_colors = COLORS["water"]
            result["water"].append(decal)

    # ---- parking lots: flush decal at grade, straight from each lot's own
    # polygon -- no groove cut (matches roads), and no small-lot fallback
    # needed anymore since a decal always exists regardless of lot size. ----
    if pk is not None and len(pk):
        for geom_utm in pk["geometry"]:
            if geom_utm.is_empty:
                continue
            tz = bg.terrain_z_mm(geom_utm.centroid.x, geom_utm.centroid.y)
            geom_local = xf(geom_utm)
            if geom_local.is_empty:
                continue
            parts = geom_local.geoms if isinstance(geom_local, BaseMultipartGeometry) else [geom_local]
            for part in parts:
                if part.is_empty or part.area <= 0:
                    continue
                try:
                    decal = trimesh.creation.extrude_polygon(part, height=DECAL_HEIGHT_MM, engine="earcut")
                except Exception:
                    continue
                decal.apply_translation([0, 0, tz + DECAL_LIFT_MM])
                decal.visual.face_colors = COLORS["parking"]
                result["parking"].append(decal)

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
                print(f"  [{tile_name}] water recess cut failed, terrain stays uncut: {e}")

    plate_mesh.visual.face_colors = COLORS["terrain"]  # uniform now -- no more per-face classification
    result["terrain"].append(plate_mesh)

    for _, row in b.iterrows():
        geom_utm = row["geometry"]
        tz = bg.terrain_z_mm(geom_utm.centroid.x, geom_utm.centroid.y)
        geom = xf(geom_utm)
        polys = geom.geoms if isinstance(geom, BaseMultipartGeometry) else [geom]
        h_mm = max(row["height_m"] * bg.METERS_TO_MM, bg.MIN_BUILDING_HEIGHT_MM)
        cat = effective_category(row["category"], row["zoning_cat"])
        color = category_color(cat)
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
            result[cat].append(m)

    global_ox, global_oy = (ox - bg.CX) * bg.MM_PER_M, (oy - bg.CY) * bg.MM_PER_M
    tile_result = {}
    for cat, meshes in result.items():
        if not meshes:
            continue
        merged = trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0]
        merged.apply_translation([global_ox, global_oy, 0])
        tile_result[cat] = merged
    return tile_result


if __name__ == "__main__":
    os.makedirs("output/colored", exist_ok=True)
    all_by_category = {cat: [] for cat in CATEGORIES}
    n_tiles_built = 0
    for tname, clipped in bg.tiles:
        print(f"building {tname} ...")
        tile_result = build_colored_tile(tname, clipped)
        if tile_result is None:
            print("  -> empty, skipped")
            continue
        n_tiles_built += 1
        for cat, mesh in tile_result.items():
            all_by_category[cat].append(mesh)
        print(f"  -> categories present: {sorted(tile_result.keys())}")

    print(f"\n{n_tiles_built}/{len(bg.tiles)} tiles had content; merging per category ...")
    scene = trimesh.Scene()
    for cat in CATEGORIES:
        meshes = all_by_category[cat]
        if not meshes:
            print(f"  {cat}: no geometry anywhere, omitted from the scene")
            continue
        merged = trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0]
        scene.add_geometry(merged, node_name=cat, geom_name=cat)
        print(f"  {cat}: {len(merged.faces)} faces")

    print(f"\nfull scene bounds={scene.bounds.tolist()}")
    scene.export("output/colored/full_disk_colored.glb")
    print("wrote output/colored/full_disk_colored.glb")
