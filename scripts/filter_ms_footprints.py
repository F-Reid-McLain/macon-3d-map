"""Stream-filter Microsoft's building footprints down to our Bibb County
extent.

Microsoft's distribution format changed since this script was last written:
it used to ship one big per-state GeoJSON file (~1.1GB for Georgia, hence
the old docstring/filename here); as of the current dataset-links.csv
(https://bfppub.blob.core.windows.net/%24web/2026-07-24/dataset-links.csv)
it's partitioned into gzip-compressed geojsonl files by Bing Maps quadkey
(zoom level 9) instead. Bibb County fits inside just 2 such tiles --
032003220 and 032003221, ~13MB + ~10MB compressed, found by converting the
county's bounding-box corners to quadkeys with the standard Bing tile-system
formula -- so this no longer needs to stream-scan a full state file; it just
reads those 2 known partitions directly. If the county boundary or the
dataset's tiling ever changes, recompute the quadkeys (see conversation/git
history for the lat/lon-to-quadkey helper used) rather than assuming these
two stay correct forever.

Bonus: this newer format includes a real per-building `height` property
(Vexcel-imagery-derived), which the old format didn't -- merge_footprints.py
picks this up automatically as `ms_height_m`.

Run from the project root: `python3 scripts/filter_ms_footprints.py`
"""
import gzip
import json

import geopandas as gpd

# Bibb County's real bounds + 3% margin, read dynamically (not hardcoded) from
# the same boundary file build_grid.py/fetch_osm.py use, so all three can't
# drift apart
_county = gpd.read_file("county_boundary/bibb_county.geojson").to_crs("EPSG:4326")
_minx, _miny, _maxx, _maxy = _county.total_bounds
_padx, _pady = (_maxx - _minx) * 0.03, (_maxy - _miny) * 0.03
WEST, SOUTH, EAST, NORTH = _minx - _padx, _miny - _pady, _maxx + _padx, _maxy + _pady

IN_PATHS = [
    "data/ms_footprints/quadkey_032003220.csv.gz",
    "data/ms_footprints/quadkey_032003221.csv.gz",
]
OUT_PATH = "data/ms_footprints_macon.geojson"


def geom_bbox(coords):
    """coords: the raw Polygon 'coordinates' list (list of rings of [lon,lat])"""
    lons = [pt[0] for ring in coords for pt in ring]
    lats = [pt[1] for ring in coords for pt in ring]
    return min(lons), min(lats), max(lons), max(lats)


def main():
    print(f"bbox: south={SOUTH:.4f} west={WEST:.4f} north={NORTH:.4f} east={EAST:.4f}")
    kept = []
    n_seen = 0
    for path in IN_PATHS:
        with gzip.open(path, "rt") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                n_seen += 1
                if n_seen % 500000 == 0:
                    print(f"scanned {n_seen} features, kept {len(kept)} so far...")
                try:
                    feat = json.loads(line)
                except json.JSONDecodeError:
                    continue
                geom = feat.get("geometry")
                if not geom or geom.get("type") != "Polygon":
                    continue
                minx, miny, maxx, maxy = geom_bbox(geom["coordinates"])
                if maxx < WEST or minx > EAST or maxy < SOUTH or miny > NORTH:
                    continue
                kept.append(feat)

    print(f"total scanned: {n_seen}, kept: {len(kept)}")
    out = {"type": "FeatureCollection", "features": kept}
    with open(OUT_PATH, "w") as f:
        json.dump(out, f)
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
