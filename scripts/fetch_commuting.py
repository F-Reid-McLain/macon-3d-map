"""Fetch Census LODES workplace/residence job counts for Bibb County block
groups, for build_colored_disk.py's "workforce geography" overlay -- where
Macon's jobs are actually located vs. where the people who hold them live.

An actual origin-destination COMMUTE FLOW map (lines connecting home block
to work block) was tried first and abandoned: real commute flows here are
genuinely diffuse, not concentrated into a few dominant corridors -- 56,784
distinct block-group-to-block-group pairs touch Bibb County, and even the
top 500 by volume account for only ~15.6% of total commuting. A "draw the
biggest flows" map would either be an unreadable tangle of thousands of
lines, or a small, arbitrary-looking sample that misrepresents how spread
out commuting into/out of the county actually is. Two density layers
(jobs located here / workers living here) is the honest version of the same
underlying question -- reuses the same choropleth architecture as
build_demographics_layers() instead of needing new line-geometry rendering.

Two variables, both raw counts (not percentages, like median_household_income
already is elsewhere in this pipeline) since "how many jobs/workers are
physically here" is the actual question, not a share of something:
  - jobs_total: total jobs located in the block group (LODES WAC, workplace
    area characteristics, field C000).
  - workers_total: total employed residents living in the block group
    (LODES RAC, residence area characteristics, field C000).

Data source: Census LEHD Origin-Destination Employment Statistics (LODES8),
2022, Georgia state file (https://lehd.ces.census.gov/data/lodes/LODES8/ga/)
-- small flat CSV.GZ files (~1.5MB WAC, ~4MB RAC for the whole state), no
API key needed, unlike the ACS demographics fetch. Boundaries come from the
same Census TIGERweb service fetch_demographics.py already uses.

Run from the project root: `python3 scripts/fetch_commuting.py`
"""
import gzip
import io

import geopandas as gpd
import pandas as pd
import requests

STATE_ABBR = "ga"
COUNTY_PREFIX = "13021"  # state 13 + county 021, first 5 digits of a block geocode
LODES_YEAR = 2022
OUT_PATH = "data/commuting_raw.geojson"

WAC_URL = f"https://lehd.ces.census.gov/data/lodes/LODES8/{STATE_ABBR}/wac/{STATE_ABBR}_wac_S000_JT00_{LODES_YEAR}.csv.gz"
RAC_URL = f"https://lehd.ces.census.gov/data/lodes/LODES8/{STATE_ABBR}/rac/{STATE_ABBR}_rac_S000_JT00_{LODES_YEAR}.csv.gz"

TIGERWEB_BLOCK_GROUPS_URL = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Tracts_Blocks/MapServer/5/query"
)


def fetch_lodes_by_block_group(url, geocode_col):
    print(f"fetching {url} ...")
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    with gzip.open(io.BytesIO(r.content)) as f:
        df = pd.read_csv(f, dtype={geocode_col: str})
    df = df[df[geocode_col].str.startswith(COUNTY_PREFIX)].copy()
    df["GEOID"] = df[geocode_col].str[:12]  # block -> block group (drop the last 3 digits)
    by_bg = df.groupby("GEOID")["C000"].sum()
    print(f"  {len(df)} Bibb County blocks -> {len(by_bg)} block groups")
    return by_bg


def fetch_boundaries():
    print("fetching TIGERweb block group boundaries ...")
    params = {
        "where": f"STATE='13' AND COUNTY='021'",
        "outFields": "GEOID",
        "f": "geojson",
        "outSR": "4326",
    }
    r = requests.get(TIGERWEB_BLOCK_GROUPS_URL, params=params, timeout=60)
    r.raise_for_status()
    gdf = gpd.GeoDataFrame.from_features(r.json()["features"], crs="EPSG:4326")
    print(f"{len(gdf)} block group boundaries")
    return gdf


def main():
    jobs = fetch_lodes_by_block_group(WAC_URL, "w_geocode").rename("jobs_total")
    workers = fetch_lodes_by_block_group(RAC_URL, "h_geocode").rename("workers_total")
    boundaries = fetch_boundaries()

    merged = boundaries.merge(jobs, on="GEOID", how="left").merge(workers, on="GEOID", how="left")
    print(f"{len(merged)} block groups total")
    for col in ["jobs_total", "workers_total"]:
        n_missing = merged[col].isna().sum()
        print(f"  {col}: {len(merged) - n_missing} values, {n_missing} block groups with no LODES data (no jobs/workers there)")

    merged.to_file(OUT_PATH, driver="GeoJSON")
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
