"""Assign each building a neighborhood height-zone (Downtown / Vineville-style
residential / College Hill / Mercer / Medical), then set a height for any
building that doesn't have a real OSM height/level tag, based on that zone's
typical character plus how large the building's own footprint is relative to
its neighbors in the same zone (bigger footprint -> more likely to be one of
the zone's taller/larger buildings).

Anchors below were derived from real coordinates of tagged buildings/streets
in our own OSM extract (Mercer's dorms/engineering building, Vineville Ave,
College St/Coleman Ave, downtown landmarks, the two hospitals) -- not
guessed blind.

Runs AFTER merge_footprints.py, on the merged 'ms' and 'hybrid' datasets (not
before), so Microsoft gap-fill buildings get the same neighborhood-aware
height treatment as the original OSM buildings, instead of a flat fallback.
Run from the project root: `python3 scripts/assign_zones.py`
"""
import geopandas as gpd
import numpy as np
from pyproj import Transformer

UTM_CRS = "EPSG:32617"

# (name, lon, lat, profile)
ANCHORS = [
    ("downtown", -83.630, 32.838, "DOWNTOWN"),
    ("college_hill", -83.641, 32.833, "COLLEGE_HILL"),
    ("mercer", -83.651, 32.828, "MERCER"),
    ("medical_navicent", -83.636, 32.834, "MEDICAL"),
    ("medical_coliseum", -83.618, 32.847, "MEDICAL"),
    ("vineville", -83.652, 32.844, "RESIDENTIAL"),
    ("south_macon", -83.635, 32.805, "RESIDENTIAL"),
    ("east_macon", -83.618, 32.828, "RESIDENTIAL"),
    ("north_fringe", -83.640, 32.850, "RESIDENTIAL"),
]

# profile: base height (m), optional mid tier (height, percentile cutoff),
# large tier (height, percentile cutoff) -- percentile is the building's own
# footprint-area rank among "default_by_type" buildings in the same zone
PROFILES = {
    # "largely all 3-4 story ... then some really large ones"
    "DOWNTOWN": dict(base=12.5, mid=None, large=(24.0, 90)),
    # "two story building with some large three stories and the occasional
    # 5-8 story apartment complex" -- this is the Vineville / generic
    # residential profile
    "RESIDENTIAL": dict(base=7.0, mid=(10.5, 70), large=(24.0, 97)),
    "COLLEGE_HILL": dict(base=7.0, mid=(10.5, 75), large=(18.0, 95)),
    "MERCER": dict(base=9.0, mid=None, large=(16.0, 88)),
    "MEDICAL": dict(base=9.5, mid=None, large=(22.0, 85)),
}

ALWAYS_TALL_MIN = {"hospital": 20.0, "university": 14.0}

to_utm = Transformer.from_crs("EPSG:4326", UTM_CRS, always_xy=True)
ANCHOR_XY = np.array([to_utm.transform(lon, lat) for _, lon, lat, _ in ANCHORS])
ANCHOR_NAMES = [a[0] for a in ANCHORS]
ANCHOR_PROFILES = [a[3] for a in ANCHORS]


def _rankdata_pct(values):
    """percentile rank (0-100) of each value within the array, ties get equal rank"""
    order = np.argsort(values)
    ranks = np.empty(len(values), dtype=float)
    ranks[order] = np.arange(1, len(values) + 1)
    return ranks / len(values) * 100


def zone_correct(in_path, out_path):
    b = gpd.read_file(in_path)
    print(f"\n[{in_path}] loaded {len(b)} buildings")
    b_utm = b.to_crs(UTM_CRS)
    centroids = b_utm.geometry.centroid
    cx, cy = centroids.x.to_numpy(), centroids.y.to_numpy()

    dists = np.sqrt((cx[:, None] - ANCHOR_XY[:, 0][None, :]) ** 2 +
                     (cy[:, None] - ANCHOR_XY[:, 1][None, :]) ** 2)
    nearest = dists.argmin(axis=1)
    b["zone_anchor"] = [ANCHOR_NAMES[i] for i in nearest]
    b["zone_profile"] = [ANCHOR_PROFILES[i] for i in nearest]
    footprint_area_m2 = b_utm.geometry.area.to_numpy()

    # "default_by_type" = untagged OSM buildings; "ms_gap_fill" = Microsoft
    # footprints added in merge_footprints.py that have no OSM match at all --
    # both need a zone-based height, neither has any real tag to trust
    is_default = b["height_src"].isin(["default_by_type", "ms_gap_fill"]).to_numpy()
    print(f"buildings needing a zone-based height: {is_default.sum()} / {len(b)}")

    new_height = b["height_m"].to_numpy(copy=True).astype(float)
    new_src = b["height_src"].to_numpy(copy=True).astype(object)

    for profile_name, profile in PROFILES.items():
        mask = is_default & (b["zone_profile"] == profile_name).to_numpy()
        if not mask.any():
            continue
        areas = footprint_area_m2[mask]
        pct = _rankdata_pct(areas)
        heights = np.full(mask.sum(), profile["base"], dtype=float)
        tiers = np.full(mask.sum(), "zone_base", dtype=object)
        if profile["mid"] is not None:
            mid_h, mid_cut = profile["mid"]
            sel = pct >= mid_cut
            heights[sel] = mid_h
            tiers[sel] = "zone_mid"
        large_h, large_cut = profile["large"]
        sel = pct >= large_cut
        heights[sel] = large_h
        tiers[sel] = "zone_large"

        idx = np.where(mask)[0]
        new_height[idx] = heights
        new_src[idx] = tiers

    # hospital/university buildings always get at least their minimum tall
    # height, regardless of zone/percentile tier (explicit exceptions)
    for btype, min_h in ALWAYS_TALL_MIN.items():
        mask = is_default & (b["btype"] == btype).to_numpy()
        for i in np.where(mask)[0]:
            if new_height[i] < min_h:
                new_height[i] = min_h
                new_src[i] = "zone_type_override"

    b["height_m"] = new_height
    b["height_src"] = new_src
    b.to_file(out_path, driver="GeoJSON")
    print(f"wrote {out_path}")
    print(b["height_src"].value_counts())
    return b


if __name__ == "__main__":
    zone_correct("data/buildings_ms.geojson", "data/buildings_ms_zoned.geojson")
    zone_correct("data/buildings_hybrid.geojson", "data/buildings_hybrid_zoned.geojson")
