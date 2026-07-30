"""Stream-filter the (1.1GB, ~4M feature) Microsoft Georgia building
footprints file down to just our downtown Macon extent, since loading the
whole state at once isn't practical. The file is one Feature JSON object per
line, so we can parse and bbox-check line by line without holding the whole
state in memory. Run from the project root: `python3 scripts/filter_ms_footprints.py`
"""
import json

# same combined extent as the 3 tiles put together, with a little margin
SOUTH, WEST, NORTH, EAST = 32.7797, -83.6882, 32.8863, -83.5618

IN_PATH = "data/ms_footprints/Georgia.geojson"
OUT_PATH = "data/ms_footprints_macon.geojson"


def geom_bbox(coords):
    """coords: the raw Polygon 'coordinates' list (list of rings of [lon,lat])"""
    lons = [pt[0] for ring in coords for pt in ring]
    lats = [pt[1] for ring in coords for pt in ring]
    return min(lons), min(lats), max(lons), max(lats)


def main():
    kept = []
    n_seen = 0
    with open(IN_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if not line.startswith('{"type":"Feature"'):
                continue
            n_seen += 1
            if n_seen % 500000 == 0:
                print(f"scanned {n_seen} features, kept {len(kept)} so far...")
            # cheap pre-filter before full JSON parse: our longitudes all start -83.6
            if "-83.6" not in line:
                continue
            line = line.rstrip(",")
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
