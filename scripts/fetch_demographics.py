"""Fetch Census ACS 5-year demographic estimates for Bibb County block
groups, for build_colored_disk.py's demographic overlay layers -- meant to
sit alongside the redlining overlay so today's patterns can be compared
directly against the 1938 HOLC grades (see docs/OVERLAYS.md).

Five variables, chosen either because they were explicitly requested or
because they're the most commonly-cited metrics in actual redlining-legacy
research (median income, homeownership):
  - pct_black: % of population that is Black/African American alone
    (B02001) -- shown deliberately because that's the exact dimension HOLC
    grading discriminated on, not a generic "race" composite.
  - pct_bachelors_plus: % of population 25+ with a Bachelor's degree or
    higher (B15003).
  - labor_force_participation: % of population 16+ in the labor force
    (B23025).
  - median_household_income: B19013, used directly (already a dollar value,
    not a ratio).
  - homeownership_rate: % of occupied housing units that are owner-occupied
    (B25003).

Geography is BLOCK GROUP, not tract -- closer to the neighborhood scale the
HOLC polygons were drawn at, for a fairer visual comparison. Data source is
the Census Bureau's public ACS API (https://api.census.gov/data/2022/acs/
acs5), which as of this project now requires a free API key (instant email
signup, see https://api.census.gov/data/key_signup.html) -- read from the
CENSUS_API_KEY environment variable, never hardcoded/committed.

Boundaries come from Census TIGERweb's public ArcGIS REST service
(no key needed) -- same request pattern as fetch_zoning.py already uses for
Bibb County's tax parcels, just a different host/layer.

ACS uses -666666666 as a sentinel for "not computed" (usually a block group
with too small a population/sample for a reliable estimate) -- treated as
missing (None) per-variable, not a reason to drop the whole block group.

Run from the project root: `CENSUS_API_KEY=... python3 scripts/fetch_demographics.py`
"""
import os
import geopandas as gpd
import pandas as pd
import requests

STATE_FIPS = "13"
COUNTY_FIPS = "021"
ACS_YEAR = 2022
OUT_PATH = "data/demographics_raw.geojson"

ACS_VARS = [
    "B02001_001E", "B02001_003E",                                    # race
    "B15003_001E", "B15003_022E", "B15003_023E", "B15003_024E", "B15003_025E",  # education
    "B23025_001E", "B23025_002E",                                    # labor force
    "B19013_001E",                                                   # median household income
    "B25003_001E", "B25003_002E",                                    # homeownership
]

TIGERWEB_BLOCK_GROUPS_URL = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Tracts_Blocks/MapServer/5/query"
)

MISSING = -666666666  # ACS sentinel for "not computed"


def _clean(v):
    v = float(v)
    return None if v <= MISSING else v


def fetch_acs():
    api_key = os.environ.get("CENSUS_API_KEY")
    if not api_key:
        raise SystemExit("set CENSUS_API_KEY (free key: https://api.census.gov/data/key_signup.html)")
    url = f"https://api.census.gov/data/{ACS_YEAR}/acs/acs5"
    params = {
        "get": "NAME," + ",".join(ACS_VARS),
        "for": "block group:*",
        "in": f"state:{STATE_FIPS} county:{COUNTY_FIPS} tract:*",
        "key": api_key,
    }
    print("fetching ACS 5-year estimates ...")
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    rows = r.json()
    df = pd.DataFrame(rows[1:], columns=rows[0])
    df["GEOID"] = df["state"] + df["county"] + df["tract"] + df["block group"]
    print(f"{len(df)} block groups")
    return df


def fetch_boundaries():
    print("fetching TIGERweb block group boundaries ...")
    params = {
        "where": f"STATE='{STATE_FIPS}' AND COUNTY='{COUNTY_FIPS}'",
        "outFields": "GEOID",
        "f": "geojson",
        "outSR": "4326",
    }
    r = requests.get(TIGERWEB_BLOCK_GROUPS_URL, params=params, timeout=60)
    r.raise_for_status()
    gdf = gpd.GeoDataFrame.from_features(r.json()["features"], crs="EPSG:4326")
    print(f"{len(gdf)} block group boundaries")
    return gdf


def compute_metrics(df):
    out = pd.DataFrame({"GEOID": df["GEOID"]})

    total_race = df["B02001_001E"].apply(_clean)
    black = df["B02001_003E"].apply(_clean)
    out["pct_black"] = [
        (b / t * 100) if (t and b is not None and t > 0) else None
        for b, t in zip(black, total_race)
    ]

    total_25plus = df["B15003_001E"].apply(_clean)
    bachelors_plus = (
        df["B15003_022E"].apply(_clean).fillna(0)
        + df["B15003_023E"].apply(_clean).fillna(0)
        + df["B15003_024E"].apply(_clean).fillna(0)
        + df["B15003_025E"].apply(_clean).fillna(0)
    )
    out["pct_bachelors_plus"] = [
        (b / t * 100) if (t and t > 0) else None
        for b, t in zip(bachelors_plus, total_25plus)
    ]

    total_16plus = df["B23025_001E"].apply(_clean)
    in_labor_force = df["B23025_002E"].apply(_clean)
    out["labor_force_participation"] = [
        (lf / t * 100) if (t and lf is not None and t > 0) else None
        for lf, t in zip(in_labor_force, total_16plus)
    ]

    out["median_household_income"] = df["B19013_001E"].apply(_clean)

    total_occupied = df["B25003_001E"].apply(_clean)
    owner_occupied = df["B25003_002E"].apply(_clean)
    out["homeownership_rate"] = [
        (o / t * 100) if (t and o is not None and t > 0) else None
        for o, t in zip(owner_occupied, total_occupied)
    ]

    return out


def main():
    acs = fetch_acs()
    metrics = compute_metrics(acs)
    boundaries = fetch_boundaries()

    merged = boundaries.merge(metrics, on="GEOID", how="inner")
    print(f"{len(merged)} block groups with matched geometry")
    for col in ["pct_black", "pct_bachelors_plus", "labor_force_participation",
                "median_household_income", "homeownership_rate"]:
        n_missing = merged[col].isna().sum()
        print(f"  {col}: {len(merged) - n_missing} values, {n_missing} missing/suppressed")

    merged.to_file(OUT_PATH, driver="GeoJSON")
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
