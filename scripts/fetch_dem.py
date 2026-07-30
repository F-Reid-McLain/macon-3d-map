"""Fetch a USGS 3DEP elevation raster for Bibb County, reprojected directly
to this project's working CRS (EPSG:32617, UTM 17N) via the ImageServer's
own `imageSR` param -- build_grid.py's rioxarray DEM loader uses the file's
native x/y coordinates as-is (no reprojection step of its own), so the file
on disk must already be in that CRS, not EPSG:4326.

No prior version of this script existed in the repo -- data/dem_10m.tif was
apparently fetched by hand in an earlier session and never scripted. This
fills that gap for the county-wide extent.

Resolution: 15m/px covers the whole ~646 km^2 county in one request
(~2500x2200px, comfortably under typical ImageServer per-request pixel caps)
while still resolving finer than build_grid.py's own 20m terrain-mesh sample
spacing -- no benefit to fetching sharper than what actually gets used.

Run from the project root: `python3 scripts/fetch_dem.py`
"""
import geopandas as gpd
import requests

PIXEL_SIZE_M = 15.0
UTM_CRS = "EPSG:32617"
OUT_PATH = "data/dem_10m.tif"   # kept the pre-existing filename build_grid.py expects,
                                 # even though this fetch is 15m -- see module docstring

URL = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage"


def main():
    county = gpd.read_file("county_boundary/bibb_county.geojson").to_crs(UTM_CRS)
    minx, miny, maxx, maxy = county.total_bounds
    pad = 300.0  # margin so DEM interpolation never has to extrapolate at the county edge
    minx, miny, maxx, maxy = minx - pad, miny - pad, maxx + pad, maxy + pad
    width = round((maxx - minx) / PIXEL_SIZE_M)
    height = round((maxy - miny) / PIXEL_SIZE_M)
    print(f"requesting {width}x{height}px ({width * height / 1e6:.1f} MP) at {PIXEL_SIZE_M}m/px, "
          f"bbox (utm)=({minx:.0f},{miny:.0f},{maxx:.0f},{maxy:.0f})")

    params = {
        "bbox": f"{minx},{miny},{maxx},{maxy}",
        "bboxSR": UTM_CRS.split(":")[1],
        "size": f"{width},{height}",
        "imageSR": UTM_CRS.split(":")[1],
        "format": "tiff",
        "pixelType": "F32",
        "noDataInterpretation": "esriNoDataMatchAny",
        "interpolation": "RSP_BilinearInterpolation",
        "f": "image",
    }
    r = requests.get(URL, params=params, timeout=180)
    r.raise_for_status()
    with open(OUT_PATH, "wb") as f:
        f.write(r.content)
    print(f"wrote {OUT_PATH}: {len(r.content)} bytes")


if __name__ == "__main__":
    main()
