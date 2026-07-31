"""Fetch named neighborhoods, hamlets, and industrial areas for map labels.

Extent: Bibb County's real bounding box, read from
county_boundary/bibb_county.geojson -- same source every other fetch script
uses. This matters more here than usual: an earlier attempt queried Overpass
by area *name* ("Bibb County"), which silently matched two different
counties (Georgia's and Alabama's, which share the name) and polluted the
results with Alabama towns like Brent and Centreville. Querying by bbox
instead of by name sidesteps that ambiguity entirely.

Run from the project root: `python3 scripts/fetch_places.py`
"""
import json
import time
import urllib.parse
import urllib.request

import geopandas as gpd

_county = gpd.read_file("county_boundary/bibb_county.geojson").to_crs("EPSG:4326")
_minx, _miny, _maxx, _maxy = _county.total_bounds
BBOX = (_miny, _minx, _maxy, _maxx)

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

QUERY = f"""
[out:json][timeout:60];
(
  node["place"~"^(neighbourhood|suburb|quarter|hamlet|village|town)$"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  way["landuse"~"^(industrial|commercial)$"]["name"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  relation["landuse"~"^(industrial|commercial)$"]["name"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
);
out center tags;
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
            with urllib.request.urlopen(req, timeout=90) as resp:
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
    with open("data/places_raw.json", "w") as f:
        json.dump(result, f)
    print("wrote data/places_raw.json")
