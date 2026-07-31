"""Fetch Bibb County parcel-level zoning data (ZONINGCODE field + parcel
polygon) from Macon-Bibb County's public open data portal, for coloring
buildings by zoning category (residential/commercial/industrial/etc) instead
of just the handful of OSM-tagged special categories (hospital/government/
Mercer/landmark) build_colored_disk.py already highlights.

Source: "Parcel CAMA2022" (Computer Assisted Mass Appraisal -- the county
tax assessor's parcel dataset), a publicly hosted ArcGIS FeatureServer, found
via the county's open data catalog (macon-bibb-county-open-data-maconbibb
.hub.arcgis.com/api/feed/dcat-us/1.1.json). This is the parcel/tax-assessor
layer, NOT the separate "Zoning Information" interactive map application
(gis.maconbibb.us/MBPZ518) -- that one is a Web AppBuilder app with no
directly queryable feature service; digging into its config.json pointed at
a Portal-for-ArcGIS item that requires auth this session doesn't have. The
CAMA parcel data has the same ZONINGCODE info as a plain public field, no
auth needed, and turned out to be the actually-usable path in.

68,970 parcels, ~99.6% with a non-blank ZONINGCODE. maxRecordCount is 1000,
so this pages through resultOffset. Run from the project root:
`python3 scripts/fetch_zoning.py`
"""
import json
import time
import requests

URL = "https://services2.arcgis.com/zPFLSOZ5HzUzzTQb/arcgis/rest/services/Parcel_CAMA2022/FeatureServer/0/query"
PAGE_SIZE = 1000
OUT_PATH = "data/parcels_zoning.geojson"


def fetch_all():
    features = []
    offset = 0
    while True:
        params = {
            "where": "1=1",
            "outFields": "ZONINGCODE,PARCEL_NO",
            "returnGeometry": "true",
            "outSR": 4326,
            "f": "geojson",
            "resultOffset": offset,
            "resultRecordCount": PAGE_SIZE,
        }
        for attempt in range(3):
            try:
                r = requests.get(URL, params=params, timeout=60)
                r.raise_for_status()
                data = r.json()
                break
            except Exception as e:
                print(f"  offset={offset} attempt {attempt+1} failed: {e}")
                time.sleep(2)
        else:
            raise RuntimeError(f"failed to fetch offset={offset} after 3 attempts")

        batch = data.get("features", [])
        if not batch:
            break
        features.extend(batch)
        print(f"fetched {len(features)} parcels so far...")
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return features


def main():
    features = fetch_all()
    print(f"total: {len(features)} parcels")
    out = {"type": "FeatureCollection", "features": features}
    with open(OUT_PATH, "w") as f:
        json.dump(out, f)
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
