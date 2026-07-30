"""Fetch OSM buildings, roads, and water for the downtown Macon model extent.

Extent: historic downtown Macon core, the College Hill Corridor, and the
Mercer University campus (the "wider" extent option). Run from the project
root: `python3 scripts/fetch_osm.py`
"""
import json
import time
import urllib.parse
import urllib.request

# south, west, north, east (lat/lon) -- covers the full 5.6km-radius circle
# (center -83.625,32.833) used for the fixed-scale tile grid, plus margin
BBOX = (32.7797, -83.6882, 32.8863, -83.5618)

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
