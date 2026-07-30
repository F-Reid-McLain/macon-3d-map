"""Build the 'ms' (Microsoft footprints + OSM-inherited height) and 'hybrid'
(OSM footprints + Microsoft gap-fill) building datasets, for comparison
against the existing OSM-only dataset. Run from the project root:
`python3 scripts/merge_footprints.py`
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
print(f"OSM buildings: {len(osm)}   MS buildings: {len(ms)}")

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

# ---- MS dataset: MS geometry, inherit OSM height/type where well-matched ----
ms_rows = []
n_inherited = 0
for i, row in ms.iterrows():
    match = best_overlap.get(row["ms_id"])
    if match and match[0] >= OVERLAP_RATIO_MATCH:
        osm_row = osm.iloc[match[1]]
        height_m, height_src, btype, name = (
            osm_row["height_m"], osm_row["height_src"], osm_row["btype"], osm_row["name"])
        n_inherited += 1
    else:
        height_m, height_src, btype, name = DEFAULT_HEIGHT_FALLBACK, "default_by_type", "yes", ""
    ms_rows.append({"id": f"ms_{row['ms_id']}", "height_m": height_m, "height_src": height_src,
                     "btype": btype, "name": name, "geometry": row["geometry"]})
ms_out = gpd.GeoDataFrame(ms_rows, crs=UTM_CRS).to_crs("EPSG:4326")
ms_out.to_file("data/buildings_ms.geojson", driver="GeoJSON")
print(f"MS dataset: {len(ms_out)} buildings, {n_inherited} inherited real OSM height/type "
      f"({100*n_inherited/len(ms_out):.1f}%)")

# ---- hybrid dataset: OSM as-is, plus MS buildings that are true gaps (no real OSM match) ----
gap_rows = []
for i, row in ms.iterrows():
    match = best_overlap.get(row["ms_id"])
    ratio = match[0] if match else 0.0
    if ratio < OVERLAP_RATIO_GAP:
        gap_rows.append({"id": f"msgap_{row['ms_id']}", "height_m": DEFAULT_HEIGHT_FALLBACK,
                          "height_src": "ms_gap_fill", "btype": "yes", "name": "",
                          "geometry": row["geometry"]})
gap_gdf = gpd.GeoDataFrame(gap_rows, crs=UTM_CRS).to_crs("EPSG:4326") if gap_rows else None
osm_wgs = osm.to_crs("EPSG:4326")
osm_cols = osm_wgs[["id", "height_m", "height_src", "btype", "name", "geometry"]]
if gap_gdf is not None:
    hybrid_out = gpd.GeoDataFrame(pd.concat([osm_cols, gap_gdf], ignore_index=True), crs="EPSG:4326")
else:
    hybrid_out = osm_cols
hybrid_out.to_file("data/buildings_hybrid.geojson", driver="GeoJSON")
print(f"hybrid dataset: {len(osm_wgs)} OSM + {len(gap_rows)} MS gap-fill = {len(hybrid_out)} buildings")
