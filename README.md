# Macon 3D Map

An interactive, color-coded 3D relief map of all of Bibb County, Georgia (not just downtown — see below), running entirely in the browser as one self-contained HTML file — no server, no external network calls, no build step to view it.

**Live version**: `site/downtown_macon_3d.html` — open it directly in a browser (filename is a holdover from when the model only covered downtown; kept as-is so existing links/bookmarks don't break). Also hosted on GitHub Pages (unlisted link, not publicly announced). A second, lower-memory build (`site/downtown_macon_3d_mobile.html`, coarser terrain, see `scripts/build_mobile.sh`) exists for phones — `index.html` picks between the two automatically based on pointer type.

## What it is

- Real USGS terrain (2.5x vertically exaggerated), real building footprints (OpenStreetMap + Microsoft's Bing Maps building footprints, hybridized — ~92K buildings total, clipped to the real county polygon, not a circle), roads, water, and parking lots, all at a fixed 1:12,500 scale. Roads render flush with the terrain (no groove) — this version isn't for physical printing, unlike the sibling `macon-3d-print` repo.
- Building heights: real OSM tags and Microsoft's own per-building height estimates where available (~34% of buildings), a neighborhood-aware zone heuristic elsewhere (see `scripts/assign_zones.py`) — not survey data for most buildings, but not a flat guess either.
- Color-coded: hospitals (red), government/public buildings (blue), Mercer University (orange), and named landmarks (brass) always take priority; every other building is colored by its actual zoning parcel from Bibb County's tax assessor data (residential/commercial/industrial/agricultural/other), not left flat tan — see `scripts/fetch_zoning.py`/`build_colored_disk.py`'s `classify_zoning()`. Roads (grey), parking lots (lavender-grey), water (blue), terrain (green).
- Every legend category (each building type, roads, parking, water, place labels) can be shown/hidden independently — click a row in the side panel. The model is exported as a multi-node scene specifically so this works (see `CLAUDE.md`). Building categories also have a second, independent toggle: click a category's color swatch to grey it out ("un-highlight") without hiding it.
- Data overlays: historical/statistical layers that float above the base map as their own toggleable section, distinct from the base map's own categories. 1938 HOLC redlining grades (University of Richmond's Mapping Inequality project, CC BY-NC-SA 4.0), shown alongside five present-day Census ACS demographic layers (race, education, labor force participation, income, homeownership) so today's patterns can be compared directly against the 1930s grades — see `docs/OVERLAYS.md` for data sources, license/citation, and how to add the next overlay.
- Labeled: highway routes (I-75, US 41, ...) as distinct shield badges, plus ~175 named neighborhoods, industrial areas, and smaller communities (from OpenStreetMap), all floating above the terrain and fading in by camera distance — highways and industrial areas visible from farthest away, neighborhoods at medium range, smaller communities only up close — see `scripts/fetch_places.py`/`build_labels.py`.
- A hand-rolled Three.js scene with a free-roam camera: **WASD** to move, **drag** to look around, **Q/E** for down/up, **shift** to boost speed, **scroll** to move forward/back. Pitch is clamped so you can never flip the view upside down. On touch devices, an on-screen joystick replaces WASD (push to the edge to run), pinch replaces scroll-to-zoom, and small buttons replace Q/E.
- Click any landmark in the side panel or on the model to smoothly fly the camera to it.
- The whole page — geometry, colors, fonts, Three.js + GLTFLoader + DRACOLoader, and the Draco decoder — is base64-embedded directly into one HTML file via `site/assemble.py`, so the published page has zero external dependencies (this was a deliberate constraint: it needs to run inside strict CSPs that block any external network request, including `connect-src` restrictions that block even `blob:` URL fetches). Three.js/GLTFLoader/DRACOLoader are wired together via an import map with runtime-generated `blob:` URIs (not `data:` — the real hosting platform's CSP blocks `data:` for scripts) — see `CLAUDE.md` for exactly how.

## Where this project is headed

This repo shares its data-prep pipeline with the sibling **macon-3d-print** repo (the physically-printable version), but the two are expected to diverge substantially. Now covers the whole county (clipped to the real county polygon, not the circle this started as) instead of just downtown; next up is likely more data overlays (commissioner district boundaries, school districts, flood zones — see `docs/OVERLAYS.md`), music-heritage landmarks, and/or even better building data (Overture Maps Foundation, Bibb County's own GIS). See `CLAUDE.md` for the current architecture and the reasoning behind it.

## Rebuilding the site

`county_boundary/bibb_county.geojson` (Bibb County's real boundary polygon, US Census cartographic boundary file, GEOID 13021) must exist before any of this — every other bbox is derived from it, not hardcoded. It lives outside `data/` on purpose, so it's committed instead of gitignored.

```
python3 scripts/fetch_dem.py              # -> data/dem_10m.tif (UTM 17N; no prior script for this existed)
python3 scripts/fetch_osm.py
python3 scripts/parse_osm.py
python3 scripts/filter_ms_footprints.py   # needs 2 quadkey partitions of Microsoft's Bing Maps building
                                           # footprints (~23MB total) manually downloaded into
                                           # data/ms_footprints/ first -- see that script's docstring for
                                           # how to find the right quadkeys for a different AOI; the old
                                           # ~1.2GB single-state-file format this originally targeted
                                           # doesn't exist anymore
python3 scripts/merge_footprints.py
python3 scripts/assign_zones.py
python3 scripts/fetch_zoning.py           # -> data/parcels_zoning.geojson (68,970 Bibb County tax parcels
                                           # with a ZONINGCODE field, for coloring buildings by zoning --
                                           # public ArcGIS FeatureServer, no auth, paginated fetch, ~2-3min)
python3 scripts/fetch_places.py           # -> data/places_raw.json (~200 named neighborhoods/hamlets/
                                           # industrial areas from OSM, queried by county BBOX -- not by
                                           # area name, which ambiguously matches Alabama's Bibb County too)
python3 scripts/build_labels.py           # -> output/labels.json (same lat/lon -> model-space transform
                                           # as build_grid.py; independent of the GLB, so re-running this
                                           # alone + site/assemble.py is enough after a places-only change)
python3 scripts/fetch_redlining.py        # -> data/redlining_raw.geojson (40 graded 1938 HOLC redlining
                                           # polygons for Macon, GA -- an overlay, not part of the base map;
                                           # see docs/OVERLAYS.md. Independent of the rest of the pipeline,
                                           # like fetch_places.py above)
CENSUS_API_KEY=... python3 scripts/fetch_demographics.py  # -> data/demographics_raw.geojson (136 Census
                                           # block groups x 5 ACS variables -- also an overlay, see
                                           # docs/OVERLAYS.md. Needs a free key: api.census.gov/data/key_signup.html
python3 scripts/build_colored_disk.py     # -> output/colored/full_disk_colored.glb (97 tiles, ~9M faces
                                           # for the whole county as a multi-node scene -- several minutes)
npx gltf-pipeline -i output/colored/full_disk_colored.glb -o site/full_disk_draco.glb -d --draco.compressionLevel=10 --draco.quantizePositionBits=14 --draco.quantizeColorBits=8 --draco.unifiedQuantization
python3 site/assemble.py                  # -> site/downtown_macon_3d.html (~10MB)
bash scripts/build_mobile.sh               # -> site/downtown_macon_3d_mobile.html (~9MB, coarser terrain --
                                           # separate lower-memory build for phones, see CLAUDE.md)
```

`build_colored_disk.py` imports `build_grid.py` directly for shared terrain/tile-geometry logic — keep both in `scripts/` together.

Python deps: `geopandas`, `trimesh`, `rioxarray`, `scipy`, `shapely`, `pyproj`, `numpy`, `rasterio`, `requests`, `pyarrow` (geopandas' parquet reader, needed only by `fetch_redlining.py`), plus trimesh's own `mapbox_earcut` (polygon triangulation) and `manifold3d` (boolean ops) -- both needed but not auto-installed as trimesh dependencies, easy to miss until a build fails partway through.

`site/three.module.js`, `GLTFLoader.js`, `DRACOLoader.js`, and `BufferGeometryUtils.js` are vendored from a pinned `three` release (unpkg) and checked in directly — no npm/bundler step needed to rebuild the page.

`data/`, `cache/`, and `output/` are gitignored (large, fully regenerable from the pipeline above).
