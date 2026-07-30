"""Export a color-coded version of the downtown tile (terrain + buildings,
same geometry as the real print file) as PLY and GLB -- plain STL has no
color support in the official spec, and trimesh's 3MF export turned out to
not reliably round-trip color in this environment (verified: came back grey),
so PLY (most universal for viewers) and GLB (modern, also very well
supported, and correctly preserves per-mesh color here) are used instead.

Color scheme matches render_color_map.py / render_color_3d.py: tan general
buildings, red hospitals, blue government/public, orange Mercer University,
green terrain. Road grooves are geometrically present (cut into the terrain,
same as the real print tile) but not separately colored -- they'd need
per-face tracking through the boolean cut to color just the groove floor,
which isn't done here; they show as green like the surrounding terrain.

Run from the project root: `python3 scripts/build_colored_tile.py`
"""
import sys
import numpy as np
import trimesh
from shapely.geometry import Polygon
from shapely.geometry.base import BaseMultipartGeometry

sys.path.insert(0, "scripts")
import build_grid as bg  # reuse the real tile geometry/terrain/building logic

COLORS = {
    "hospital": [214, 39, 40, 255],
    "government": [31, 78, 156, 255],
    "mercer": [242, 140, 40, 255],
    "building_default": [210, 180, 140, 255],
    "terrain": [90, 160, 90, 255],
}


def categorize(btype):
    if btype == "hospital":
        return "hospital"
    if btype in ("government", "public"):
        return "government"
    if btype in ("university", "dormitory"):
        return "mercer"
    return "building_default"


TILE_I, TILE_J = 0, 0
name = f"tile_{TILE_I:+03d}_{TILE_J:+03d}".replace("+", "p").replace("-", "m")
clip_shape_m = None
for tname, clipped in bg.tiles:
    if tname == name:
        clip_shape_m = clipped
        break
assert clip_shape_m is not None, f"tile {name} not found in grid"

b = bg.buildings_all[bg.buildings_all.intersects(clip_shape_m)].copy()
b["geometry"] = b["geometry"].intersection(clip_shape_m)
b = b[~b["geometry"].is_empty]
b["category"] = b["btype"].apply(categorize)
print(f"tile {name}: {len(b)} buildings")
print(b["category"].value_counts())

plate_clip_m = clip_shape_m.buffer(bg.PLATE_MARGIN_M)
plate_mesh, (ox, oy) = bg.build_terrain_base(plate_clip_m)
print(f"terrain base: is_volume={plate_mesh.is_volume}, faces={len(plate_mesh.faces)}")

# engrave roads into the terrain (matches the real print tile's geometry;
# not separately colored -- see module docstring)
r = bg.roads_all[bg.roads_all.intersects(clip_shape_m)].copy()
r["geometry"] = r["geometry"].intersection(clip_shape_m)
r = r[~r["geometry"].is_empty]
from shapely.affinity import affine_transform
xf = lambda g: affine_transform(g, [bg.MM_PER_M, 0, 0, bg.MM_PER_M, -ox * bg.MM_PER_M, -oy * bg.MM_PER_M])

cut_shapes = []
for line_utm in r["geometry"]:
    if line_utm.is_empty or line_utm.length == 0:
        continue
    tz = bg.terrain_z_mm(line_utm.centroid.x, line_utm.centroid.y)
    line_local = xf(line_utm)
    ribbon = line_local.buffer(bg.ROAD_GROOVE_WIDTH_MM / 2)
    parts = ribbon.geoms if isinstance(ribbon, BaseMultipartGeometry) else [ribbon]
    for part in parts:
        if part.is_empty or part.area <= 0:
            continue
        prism = trimesh.creation.extrude_polygon(part, height=bg.ROAD_GROOVE_DEPTH_MM + 1.0, engine="earcut")
        prism.apply_translation([0, 0, tz - bg.ROAD_GROOVE_DEPTH_MM])
        if prism.is_volume:
            cut_shapes.append(prism)

if cut_shapes and plate_mesh.is_volume:
    plate_mesh.merge_vertices()
    good = [c for c in cut_shapes if (c.merge_vertices() or True) and c.is_volume]
    try:
        plate_mesh = trimesh.boolean.difference([plate_mesh] + good, engine="manifold")
        print(f"engraved {len(good)} road groove(s)")
    except Exception as e:
        print(f"road groove cut failed, keeping terrain uncut: {e}")

plate_mesh.visual.face_colors = COLORS["terrain"]

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

print(f"building meshes: {len(building_meshes)}")
combined = trimesh.util.concatenate([plate_mesh] + building_meshes)
print(f"combined: faces={len(combined.faces)}, has face_colors={hasattr(combined.visual, 'face_colors')}")

combined.export("output/colored/downtown_tile_colored.ply")
combined.export("output/colored/downtown_tile_colored.glb")
print("wrote output/colored/downtown_tile_colored.ply")
print("wrote output/colored/downtown_tile_colored.glb")

# quick round-trip sanity check
check = trimesh.load("output/colored/downtown_tile_colored.ply")
print("PLY round-trip sample face colors:", check.visual.face_colors[::len(check.faces)//5][:5])
