"""Fetch OSM buildings, roads, and water for the Macon model extent.

Extent: all of Bibb County (county_boundary/bibb_county.geojson), not
just the downtown core -- widened from the original downtown-only extent
(historic core + College Hill Corridor + Mercer University) when the model
grew to cover the whole county. Run from the project root:
`python3 scripts/fetch_osm.py`
"""
import json
import time
import urllib.parse
import urllib.request

import geopandas as gpd

# south, west, north, east (lat/lon) -- Bibb County's real bounds + 3% margin,
# read from the same boundary file build_grid.py clips tiles to, not
# hardcoded, so the two can't quietly drift apart
_county = gpd.read_file("county_boundary/bibb_county.geojson").to_crs("EPSG:4326")
_minx, _miny, _maxx, _maxy = _county.total_bounds
_padx, _pady = (_maxx - _minx) * 0.03, (_maxy - _miny) * 0.03
BBOX = (_miny - _pady, _minx - _padx, _maxy + _pady, _maxx + _padx)

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

QUERY = f"""
[out:json][timeout:240];
(
  way["building"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  relation["building"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  way["highway"]["highway"!~"^(footway|cycleway|path|steps|pedestrian|bridleway|corridor|elevator|proposed|construction|planned|platform|razed)$"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  way["waterway"="river"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  way["natural"="water"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  relation["natural"="water"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  way["amenity"="parking"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  relation["amenity"="parking"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  way["aeroway"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  relation["aeroway"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
);
out body;
>;
out skel qt;
"""


def fetch():
    data = ("data=" + urllib.parse.quote(QUERY)).encode()
    headers = {
        "User-Agent": "downtown-macon-3d-map/1.0 (personal 3D printing project)",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "*/*",
    }
    last_err = None
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            print(f"trying {endpoint} ...")
            req = urllib.request.Request(endpoint, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=280) as resp:
                raw = resp.read()
            result = json.loads(raw)
            print(f"got {len(result.get('elements', []))} elements from {endpoint}")
            return result
        except Exception as e:
            print(f"  failed: {e}")
            last_err = e
            time.sleep(2)
    raise last_err


if __name__ == "__main__":
    result = fetch()
    with open("data/osm_raw.json", "w") as f:
        json.dump(result, f)
    print("wrote data/osm_raw.json")
