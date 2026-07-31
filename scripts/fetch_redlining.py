"""Fetch the 1930s HOLC (Home Owners' Loan Corporation) redlining survey
polygons for Macon, GA, for build_colored_disk.py's "redlining" overlay
layer (see CLAUDE.md / docs/OVERLAYS.md for the visual/architectural
approach).

Source: the "Mapping Inequality: Redlining in New Deal America" project
(Digital Scholarship Lab, University of Richmond), via a public GeoParquet
mirror on Source Cooperative (source.coop/cboettig/mappinginequality) --
the project's own dsl.richmond.edu static download URLs no longer serve raw
data directly (now just the SPA shell), so this mirror is the actually-
usable path in. 2.7MB, all ~200 surveyed US cities; filtered down to just
Macon, GA (41 polygons) here.

LICENSE: CC BY-NC-SA 4.0 (non-commercial, share-alike, attribution
required). Suggested citation, per the project:
  Robert K. Nelson, LaDale Winling, Richard Marciano, Nathan Connolly,
  et al., "Mapping Inequality," American Panorama, ed. Robert K. Nelson
  and Edward L. Ayers, accessed [DATE], https://dsl.richmond.edu/panorama/redlining/
See docs/OVERLAYS.md for the full attribution requirement and context on
why this data matters for Macon specifically (one of the most heavily
redlined cities in the country -- 65% of neighborhoods graded "Hazardous").

Needs `pyarrow` (geopandas' parquet reader) -- not otherwise a project
dependency, since nothing else here touches (geo)parquet.

Run from the project root: `python3 scripts/fetch_redlining.py`
"""
import tempfile
import os
import requests
import geopandas as gpd

SOURCE_URL = "https://data.source.coop/cboettig/mappinginequality/mappinginequality.parquet"
OUT_PATH = "data/redlining_raw.geojson"
CITY, STATE = "Macon", "GA"


def main():
    print(f"downloading {SOURCE_URL} ...")
    # geopandas/pyarrow's read_parquet doesn't handle a plain https:// URI
    # directly (no filesystem registered for it) -- download to a temp file
    # first, same as every other fetch script's plain requests.get() pattern.
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
        tmp_path = tmp.name
        r = requests.get(SOURCE_URL, timeout=60)
        r.raise_for_status()
        tmp.write(r.content)
    try:
        gdf = gpd.read_parquet(tmp_path)
    finally:
        os.unlink(tmp_path)
    print(f"{len(gdf)} total HOLC polygons across all surveyed cities")

    macon = gdf[(gdf["city"] == CITY) & (gdf["state"] == STATE)].copy()
    print(f"{len(macon)} polygons for {CITY}, {STATE}")
    print(macon["grade"].value_counts(dropna=False))

    # "Industrial and Commercial" areas have no letter grade (grade is None)
    # -- these were categorized by land use, not creditworthiness, and are a
    # different kind of area to what "redlining" usually refers to. Keep
    # only the four lettered residential-desirability grades (A/B/C/D).
    macon = macon[macon["grade"].isin(["A", "B", "C", "D"])]
    print(f"{len(macon)} graded (A/B/C/D) polygons kept")

    macon = macon.to_crs("EPSG:4326")
    geom_col = macon.geometry.name  # the source parquet's active geometry column is "geom", not "geometry"
    macon[["area_id", "grade", "category", "fill", geom_col]].to_file(OUT_PATH, driver="GeoJSON")
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
