"""Build the 'ms' (Microsoft footprints + OSM-inherited height) and 'hybrid'
(OSM footprints + Microsoft gap-fill) building datasets, for comparison
against the existing OSM-only dataset. Run from the project root:
`python3 scripts/merge_footprints.py`

Microsoft's newer footprints (see filter_ms_footprints.py) carry their own
per-building `height` estimate (Vexcel-imagery-derived), unlike the older
format this pipeline originally targeted. Used here as a real fallback for
buildings with no confident OSM match, in place of the flat
DEFAULT_HEIGHT_FALLBACK this used to fall back to unconditionally -- ~0.35%
of MS buildings carry a -1.0 sentinel for "no estimate", which is the only
case that still falls all the way back to the flat default.
"""
import pandas as pd
import geopandas as gpd
from shapely.geometry.base import BaseMultipartGeometry

UTM_CRS = "EPSG:32617"
OVERLAP_RATIO_MATCH = 0.3   # MS building counts as "matched" to an OSM building
                            # if the overlap covers at least this fraction of
                            # the MS building's own area
OVERLAP_RATIO_GAP = 0.05    # MS building counts as a true "gap" (no real OSM
                            # counterpart) if overlap covers less than this
DEFAULT_HEIGHT_FALLBACK = 7.0

osm = gpd.read_file("data/buildings_raw.geojson").to_crs(UTM_CRS)
ms = gpd.read_file("data/ms_footprints_macon.geojson").to_crs(UTM_CRS)
ms = ms.reset_index(drop=True)
ms["ms_id"] = ms.index
ms["ms_area"] = ms.geometry.area
# MS's own height estimate, when it has one (its -1.0 "no estimate" sentinel
# and any other non-positive value both fall back to the flat default instead)
ms["ms_height_m"] = ms["height"].where(ms["height"] > 0, DEFAULT_HEIGHT_FALLBACK)
n_ms_real = (ms["height"] > 0).sum()
print(f"OSM buildings: {len(osm)}   MS buildings: {len(ms)} "
      f"({n_ms_real} with a real MS height estimate, {len(ms) - n_ms_real} fall back to flat default)")

osm_idx = osm[["geometry"]].copy()
osm_idx["osm_row"] = osm.index

# spatial join: every (ms, osm) pair that overlaps at all
joined = gpd.sjoin(ms[["ms_id", "ms_area", "geometry"]], osm_idx, predicate="intersects", how="left")

best_overlap = {}  # ms_id -> (overlap_ratio, osm_row)
for _, row in joined.iterrows():
    if pd.isna(row["osm_row"]):
        continue
    ms_geom = ms.geometry.iloc[row["ms_id"]]
    osm_geom = osm.geometry.iloc[int(row["osm_row"])]
    inter = ms_geom.intersection(osm_geom)
    if inter.is_empty:
        continue
    ratio = inter.area / row["ms_area"] if row["ms_area"] > 0 else 0
    prev = best_overlap.get(row["ms_id"])
    if prev is None or ratio > prev[0]:
        best_overlap[row["ms_id"]] = (ratio, int(row["osm_row"]))

print(f"MS buildings with any OSM overlap: {len(best_overlap)}")

# ---- MS dataset: MS geometry, inherit OSM height/type where well-matched,
# else fall back to MS's own height estimate (height_src="ms_height" --
# NOT "default_by_type"/"ms_gap_fill", so assign_zones.py's zone-based
# height-correction pass -- which unconditionally overwrites anything tagged
# with those two sources -- leaves this alone and doesn't clobber a real
# estimate with a cruder neighborhood-percentile guess) ----
ms_rows = []
n_inherited = 0
n_ms_height = 0
for i, row in ms.iterrows():
    match = best_overlap.get(row["ms_id"])
    if match and match[0] >= OVERLAP_RATIO_MATCH:
        osm_row = osm.iloc[match[1]]
        height_m, height_src, btype, name = (
            osm_row["height_m"], osm_row["height_src"], osm_row["btype"], osm_row["name"])
        n_inherited += 1
    elif row["height"] > 0:
        height_m, height_src, btype, name = row["ms_height_m"], "ms_height", "yes", ""
        n_ms_height += 1
    else:
        height_m, height_src, btype, name = DEFAULT_HEIGHT_FALLBACK, "default_by_type", "yes", ""
    ms_rows.append({"id": f"ms_{row['ms_id']}", "height_m": height_m, "height_src": height_src,
                     "btype": btype, "name": name, "geometry": row["geometry"]})
ms_out = gpd.GeoDataFrame(ms_rows, crs=UTM_CRS).to_crs("EPSG:4326")
ms_out.to_file("data/buildings_ms.geojson", driver="GeoJSON")
print(f"MS dataset: {len(ms_out)} buildings, {n_inherited} inherited real OSM height/type "
      f"({100*n_inherited/len(ms_out):.1f}%), {n_ms_height} from MS's own height estimate "
      f"({100*n_ms_height/len(ms_out):.1f}%)")

# ---- hybrid dataset: OSM as-is, plus MS buildings that are true gaps (no real OSM
# match) -- same ms_height/ms_gap_fill split as the MS dataset above, and for the
# same reason (don't let a real MS estimate get clobbered by zone-based correction) ----
gap_rows = []
n_gap_ms_height = 0
for i, row in ms.iterrows():
    match = best_overlap.get(row["ms_id"])
    ratio = match[0] if match else 0.0
    if ratio < OVERLAP_RATIO_GAP:
        if row["height"] > 0:
            height_m, height_src = row["ms_height_m"], "ms_height"
            n_gap_ms_height += 1
        else:
            height_m, height_src = DEFAULT_HEIGHT_FALLBACK, "ms_gap_fill"
        gap_rows.append({"id": f"msgap_{row['ms_id']}", "height_m": height_m,
                          "height_src": height_src, "btype": "yes", "name": "",
                          "geometry": row["geometry"]})
gap_gdf = gpd.GeoDataFrame(gap_rows, crs=UTM_CRS).to_crs("EPSG:4326") if gap_rows else None
osm_wgs = osm.to_crs("EPSG:4326")
osm_cols = osm_wgs[["id", "height_m", "height_src", "btype", "name", "geometry"]]
if gap_gdf is not None:
    hybrid_out = gpd.GeoDataFrame(pd.concat([osm_cols, gap_gdf], ignore_index=True), crs="EPSG:4326")
else:
    hybrid_out = osm_cols
hybrid_out.to_file("data/buildings_hybrid.geojson", driver="GeoJSON")
print(f"hybrid dataset: {len(osm_wgs)} OSM + {len(gap_rows)} MS gap-fill "
      f"({n_gap_ms_height} with a real MS height estimate) = {len(hybrid_out)} buildings")
