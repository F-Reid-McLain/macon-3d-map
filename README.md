# Macon 3D Map

An interactive, color-coded 3D relief map of downtown Macon, Georgia, running entirely in the browser as one self-contained HTML file — no server, no external network calls, no build step to view it.

**Live version**: `site/downtown_macon_3d.html` — open it directly in a browser.

## What it is

- Real USGS terrain (2.5x vertically exaggerated), real building footprints (OpenStreetMap + Microsoft's US Building Footprints, hybridized), roads, water, and parking lots, all at a fixed 1:12,500 scale.
- Color-coded by category: hospitals (red), government/public buildings (blue), Mercer University (orange), named landmarks (brass), general buildings (tan), roads (grey), parking lots (lavender-grey), water (blue), terrain (green).
- Click any landmark in the side panel or on the model to fly the camera to it.
- The whole model — geometry, colors, fonts, the `<model-viewer>` library, and the Draco decoder — is base64-embedded directly into one HTML file via `site/assemble.py`, so the published page has zero external dependencies (this was a deliberate constraint: it needs to run inside strict CSPs that block any external network request, including `connect-src` restrictions that block even `blob:` URL fetches).

## Where this project is headed

This repo shares its data-prep pipeline with the sibling **macon-3d-print** repo (the physically-printable version), but the two are expected to diverge substantially: this one is moving toward a full free-roam Three.js viewer (not the orbit-only `<model-viewer>` camera it uses today), eventually covering all of Macon rather than just the downtown core, with better building data and toggleable stats overlays. See `CLAUDE.md` for the current architecture and where things are headed.

## Rebuilding the site

```
python3 scripts/fetch_osm.py
python3 scripts/parse_osm.py
python3 scripts/filter_ms_footprints.py   # needs Microsoft's US Building Footprints GeoJSON locally (not included, ~1.2GB)
python3 scripts/merge_footprints.py
python3 scripts/assign_zones.py
python3 scripts/build_colored_disk.py     # -> output/colored/full_disk_colored.glb
npx gltf-pipeline -i output/colored/full_disk_colored.glb -o site/full_disk_draco.glb -d --draco.compressionLevel=10 --draco.quantizePositionBits=14 --draco.quantizeColorBits=8 --draco.unifiedQuantization
python3 site/assemble.py                  # -> site/downtown_macon_3d.html
```

`build_colored_disk.py` imports `build_grid.py` directly for shared terrain/tile-geometry logic — keep both in `scripts/` together.

`data/`, `cache/`, and `output/` are gitignored (large, fully regenerable from the pipeline above).
