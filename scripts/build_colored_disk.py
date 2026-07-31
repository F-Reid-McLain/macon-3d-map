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
import pandas as pd
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

# 1930s HOLC redlining grades -- see scripts/fetch_redlining.py and
# docs/OVERLAYS.md for the data source, license, and context. Colors are the
# dataset's own "fill" field, which is itself the traditional HOLC scheme
# (green/blue/yellow/red) -- kept as-is rather than re-picking colors, since
# that scheme is what makes a redlining map immediately recognizable as one.
REDLINING_COLORS = {
    "redlining_a": [118, 168, 101, 255],  # "Best" -- #76a865
    "redlining_b": [124, 181, 189, 255],  # "Still Desirable" -- #7cb5bd
    "redlining_c": [255, 255, 0, 255],    # "Definitely Declining" -- #ffff00
    "redlining_d": [217, 131, 141, 255],  # "Hazardous" (i.e. redlined) -- #d9838d
}
REDLINING_GRADE_TO_NODE = {"A": "redlining_a", "B": "redlining_b", "C": "redlining_c", "D": "redlining_d"}

# Census ACS demographic overlays -- see scripts/fetch_demographics.py and
# docs/OVERLAYS.md. Unlike redlining's 4 fixed A-D grades, these are
# continuous values, so each block group is bucketed into 5 quantile classes
# (roughly equal COUNTS of block groups per class, standard choropleth
# practice) and colored from a 5-step sequential ramp (ColorBrewer palettes)
# -- but unlike redlining, all 5 buckets of one variable share ONE scene
# node/legend row (toggle the whole variable at once, not bucket-by-bucket --
# 5 variables x 5 buckets as 25 separate toggle rows would be unusable).
# Ramps deliberately avoid hues already load-bearing elsewhere in the legend
# (terrain/agricultural green, water/redlining-B blue, commercial purple) --
# race uses a neutral grey specifically so the color encodes MAGNITUDE only,
# not an implied value judgment about the demographic itself.
DEMOGRAPHIC_VARS = [
    ("pct_black", "demo_race_black"),
    ("pct_bachelors_plus", "demo_education"),
    ("labor_force_participation", "demo_labor_force"),
    ("median_household_income", "demo_income"),
    ("homeownership_rate", "demo_homeownership"),
]
DEMOGRAPHIC_COLOR_RAMPS = {
    "demo_race_black": [[247, 247, 247, 255], [204, 204, 204, 255], [150, 150, 150, 255], [99, 99, 99, 255], [37, 37, 37, 255]],
    "demo_education": [[242, 240, 247, 255], [203, 201, 226, 255], [158, 154, 200, 255], [117, 107, 177, 255], [84, 39, 143, 255]],
    "demo_labor_force": [[254, 237, 222, 255], [253, 190, 133, 255], [253, 141, 60, 255], [230, 85, 13, 255], [166, 54, 3, 255]],
    "demo_income": [[239, 243, 255, 255], [189, 215, 231, 255], [107, 174, 214, 255], [49, 130, 189, 255], [8, 81, 156, 255]],
    "demo_homeownership": [[237, 248, 233, 255], [186, 228, 179, 255], [116, 196, 118, 255], [49, 163, 84, 255], [0, 109, 44, 255]],
}

# Every node name that ends up in the exported Scene, in legend order -- also
# the exact set of names site/template.html looks for when wiring up toggle
# checkboxes. "terrain" is deliberately NOT toggleable in the UI (hiding the
# ground plane isn't useful), but it's still its own node for consistency.
CATEGORIES = [
    "terrain", "water", "road", "parking",
    "hospital", "government", "mercer", "landmark",
    "residential", "commercial", "industrial", "agricultural", "other", "unclassified",
    "redlining_a", "redlining_b", "redlining_c", "redlining_d",
    "demo_race_black", "demo_education", "demo_labor_force", "demo_income", "demo_homeownership",
]

DECAL_HEIGHT_MM = 0.12
DECAL_LIFT_MM = 0.03  # clears the decal off the terrain surface it sits on -- avoids z-fighting

# Roads get a bigger lift than other decals: measured directly (sampling
# thousands of road vertices and raycasting straight down against the
# rendered terrain mesh) that DECAL_LIFT_MM alone left ~21% of the road
# BELOW the terrain surface, down to -0.32mm at the worst points. Cause:
# the terrain MESH is a triangulated grid (each DEM cell split by one
# diagonal into two flat triangles), but terrain_z_mm_batch samples true
# bilinear interpolation -- the two don't exactly agree at sub-cell
# precision, and 0.03mm is nowhere near enough margin to cover that noise
# for a shape as large/varied as the whole road network. 0.45mm comfortably
# clears the measured worst case with headroom.
ROAD_DECAL_LIFT_MM = 0.45

# Real-world road widths (meters) by OSM class, used for the road decal --
# was a single flat 3.0mm (37.5 real meters!) for every road regardless of
# class, which read as one giant blobby mass. Combined with flat caps/mitre
# joins (not shapely's default round) at the buffer() call site, this keeps
# bends from tessellating into fat circular bulges too.
ROAD_WIDTH_M = {
    "motorway": 16, "trunk": 16, "primary": 14,
    "motorway_link": 10, "trunk_link": 10, "primary_link": 10,
    "secondary": 11, "tertiary": 9,
    "secondary_link": 8, "tertiary_link": 8,
}
ROAD_WIDTH_DEFAULT_M = 6  # residential/service/unclassified/living_street/road/track
REDLINING_LIFT_MM = 25.0  # clears typical rooftops (tallest building in this model is ~21mm) -- these
                           # are neighborhood-scale historical boundaries, meant to read as a translucent
                           # wash hovering over an area regardless of what's built there today, not a
                           # ground-hugging decal like roads/water/parking.


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


def drape_polygon_mesh(poly_utm, ox, oy, lift_mm, color):
    """Triangulate a shapely polygon (in UTM meters) and drape it onto the
    real terrain surface -- each VERTEX gets its own sampled height instead
    of extruding the whole shape flat at one representative height, which
    floats above dips / clips through rises wherever a shape spans more
    elevation change than that one sample point captured (very visible on
    Macon's real river bluff with the old flat-extruded road decal). Because
    height comes from the same continuous terrain function at each vertex's
    real (x,y), two separately-draped shapes that happen to share a boundary
    point land on the identical height there too -- no visible seam between
    them, without needing to actually be one merged mesh."""
    verts2d, faces = trimesh.creation.triangulate_polygon(poly_utm, engine="earcut")
    if len(faces) == 0:
        return None
    z_mm = bg.terrain_z_mm_batch(verts2d[:, 0], verts2d[:, 1]) + lift_mm
    x_mm = (verts2d[:, 0] - ox) * bg.MM_PER_M
    y_mm = (verts2d[:, 1] - oy) * bg.MM_PER_M
    mesh = trimesh.Trimesh(vertices=np.column_stack([x_mm, y_mm, z_mm]), faces=faces, process=False)
    # earcut's vertex winding isn't guaranteed to face +z -- flip if the
    # average face normal points down instead of up.
    if mesh.face_normals[:, 2].mean() < 0:
        mesh.faces = mesh.faces[:, ::-1]
    mesh.visual.face_colors = color
    return mesh


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

    # ---- roads: thin decal DRAPED onto the real terrain (see
    # drape_polygon_mesh) instead of extruded flat at one sampled height --
    # the flat-extrude version floated above dips / clipped through rises
    # wherever a merged road shape spanned more elevation change than its
    # one height sample captured, very visible on Macon's real river bluff.
    # Draping means per-vertex height comes from a continuous function, so
    # it's now safe to union the WHOLE tile's road network into as few
    # disjoint shapes as possible for face-count efficiency (like before)
    # without that costing terrain-following accuracy the way it used to --
    # extruding each segment separately instead measured 1.08M faces for
    # just 3 tiles' worth of roads, more than the entire terrain mesh for
    # the same area, from the fixed top+bottom+wall overhead every separate
    # extrude_polygon() call pays.
    #
    # Width is tiered by real OSM road class (ROAD_WIDTH_M) instead of one
    # flat value for every road regardless of class, and the buffer uses
    # flat caps + mitre joins (not shapely's default round) so bends don't
    # tessellate into fat circular bulges. ----
    road_ribbons_utm = []
    for line_utm, road_class in zip(r["geometry"], r["class"]):
        if line_utm.is_empty or line_utm.length == 0:
            continue
        width_m = ROAD_WIDTH_M.get(road_class, ROAD_WIDTH_DEFAULT_M)
        road_ribbons_utm.append(line_utm.buffer(width_m / 2, cap_style="flat", join_style="mitre"))
    road_union_utm = unary_union(road_ribbons_utm) if road_ribbons_utm else None
    if road_union_utm is not None and not road_union_utm.is_empty:
        clusters = road_union_utm.geoms if isinstance(road_union_utm, BaseMultipartGeometry) else [road_union_utm]
        for cluster_utm in clusters:
            if cluster_utm.is_empty or cluster_utm.area <= 0:
                continue
            try:
                decal = drape_polygon_mesh(cluster_utm, ox, oy, ROAD_DECAL_LIFT_MM, COLORS["road"])
            except Exception:
                continue
            if decal is not None:
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


def build_redlining_layer():
    """Returns {redlining_a/b/c/d: mesh} for whichever grades are present.
    Unlike everything else in this file, this isn't processed per-tile
    (bg.tiles) -- there are only 40 polygons total for the whole county, so
    one pass over the raw data is simpler and plenty fast. Each polygon
    becomes its own thin decal floating REDLINING_LIFT_MM above the local
    terrain height at its centroid (see that constant's comment), grouped by
    letter grade into one mesh per grade so each is independently
    toggleable in the legend."""
    path = "data/redlining_raw.geojson"
    if not os.path.exists(path):
        print("no data/redlining_raw.geojson -- run scripts/fetch_redlining.py first; skipping this layer")
        return {}

    gdf = gpd.read_file(path).to_crs(bg.UTM_CRS)
    by_grade = {node: [] for node in REDLINING_GRADE_TO_NODE.values()}
    for _, row in gdf.iterrows():
        node = REDLINING_GRADE_TO_NODE.get(row["grade"])
        if node is None:
            continue
        geom_utm = row["geometry"]
        if geom_utm.is_empty:
            continue
        tz = bg.terrain_z_mm(geom_utm.centroid.x, geom_utm.centroid.y) + REDLINING_LIFT_MM
        geom_local = affine_transform(geom_utm, [bg.MM_PER_M, 0, 0, bg.MM_PER_M, -bg.CX * bg.MM_PER_M, -bg.CY * bg.MM_PER_M])
        parts = geom_local.geoms if isinstance(geom_local, BaseMultipartGeometry) else [geom_local]
        for part in parts:
            if part.is_empty or part.area <= 0:
                continue
            try:
                decal = trimesh.creation.extrude_polygon(part, height=DECAL_HEIGHT_MM, engine="earcut")
            except Exception:
                continue
            decal.apply_translation([0, 0, tz])
            decal.visual.face_colors = REDLINING_COLORS[node]
            by_grade[node].append(decal)

    result = {}
    for node, decals in by_grade.items():
        if not decals:
            continue
        result[node] = trimesh.util.concatenate(decals) if len(decals) > 1 else decals[0]
    return result


def build_demographics_layers():
    """Returns {demo_race_black/education/labor_force/income/homeownership:
    mesh} for whichever variables have data. Same not-tiled, decal-at-
    REDLINING_LIFT_MM approach as build_redlining_layer() (136 Census block
    group polygons total for the whole county -- cheap enough for one pass),
    but each variable's block groups are quantile-bucketed into 5 classes
    and colored from that variable's sequential ramp (DEMOGRAPHIC_COLOR_RAMPS)
    instead of 4 fixed letter-grade colors, and ALL 5 buckets of one variable
    merge into one scene node/legend toggle (see DEMOGRAPHIC_VARS comment)."""
    path = "data/demographics_raw.geojson"
    if not os.path.exists(path):
        print("no data/demographics_raw.geojson -- run scripts/fetch_demographics.py first; skipping this layer")
        return {}

    gdf = gpd.read_file(path).to_crs(bg.UTM_CRS)
    result = {}
    for col, node in DEMOGRAPHIC_VARS:
        valid = gdf[gdf[col].notna()].copy()
        if len(valid) == 0:
            continue
        # quantile buckets: roughly equal COUNTS of block groups per class,
        # standard choropleth practice -- not equal-width value ranges, which
        # a single outlier block group could badly skew.
        valid["bucket"] = pd.qcut(valid[col], 5, labels=False, duplicates="drop")
        ramp = DEMOGRAPHIC_COLOR_RAMPS[node]

        decals = []
        for _, row in valid.iterrows():
            geom_utm = row["geometry"]
            if geom_utm.is_empty:
                continue
            tz = bg.terrain_z_mm(geom_utm.centroid.x, geom_utm.centroid.y) + REDLINING_LIFT_MM
            geom_local = affine_transform(geom_utm, [bg.MM_PER_M, 0, 0, bg.MM_PER_M, -bg.CX * bg.MM_PER_M, -bg.CY * bg.MM_PER_M])
            parts = geom_local.geoms if isinstance(geom_local, BaseMultipartGeometry) else [geom_local]
            for part in parts:
                if part.is_empty or part.area <= 0:
                    continue
                try:
                    decal = trimesh.creation.extrude_polygon(part, height=DECAL_HEIGHT_MM, engine="earcut")
                except Exception:
                    continue
                decal.apply_translation([0, 0, tz])
                decal.visual.face_colors = ramp[int(row["bucket"])]
                decals.append(decal)

        if decals:
            result[node] = trimesh.util.concatenate(decals) if len(decals) > 1 else decals[0]
    return result


if __name__ == "__main__":
    # OUTPUT_GLB_PATH lets the same script build a second, coarser "mobile"
    # variant (via DEM_SAMPLE_SPACING_M, see build_grid.py) without
    # overwriting the desktop one -- see scripts/build_mobile.sh.
    out_path = os.environ.get("OUTPUT_GLB_PATH", "output/colored/full_disk_colored.glb")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
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

    print("\nbuilding redlining overlay (not tiled -- 40 polygons total) ...")
    for node, mesh in build_redlining_layer().items():
        all_by_category[node].append(mesh)
        print(f"  {node}: {len(mesh.faces)} faces")

    # SKIP_DEMOGRAPHICS_OVERLAY lets the mobile build (see build_mobile.sh)
    # drop these entirely -- they default to hidden (site/template.html's
    # LEGEND_SECTIONS `defaultOff: true`), but Three.js keeps hidden geometry
    # fully resident in GPU memory regardless, so on a memory-constrained
    # device they cost real memory for zero visible benefit on first load.
    if os.environ.get("SKIP_DEMOGRAPHICS_OVERLAY") != "1":
        print("\nbuilding demographics overlays (not tiled -- 136 block groups total) ...")
        for node, mesh in build_demographics_layers().items():
            all_by_category[node].append(mesh)
            print(f"  {node}: {len(mesh.faces)} faces")
    else:
        print("\nSKIP_DEMOGRAPHICS_OVERLAY=1 -- omitting demographics overlays from this build")

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
    scene.export(out_path)
    print(f"wrote {out_path}")
