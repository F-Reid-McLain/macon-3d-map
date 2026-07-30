# Macon 3D Map

An interactive, color-coded 3D relief map of downtown Macon, Georgia, running entirely in the browser as one self-contained HTML file — no server, no external network calls, no build step to view it.

**Live version**: `site/downtown_macon_3d.html` — open it directly in a browser.

## What it is

- Real USGS terrain (2.5x vertically exaggerated), real building footprints (OpenStreetMap + Microsoft's US Building Footprints, hybridized), roads, water, and parking lots, all at a fixed 1:12,500 scale. Roads render flush with the terrain (no groove) — this version isn't for physical printing, unlike the sibling `macon-3d-print` repo.
- Color-coded by category: hospitals (red), government/public buildings (blue), Mercer University (orange), named landmarks (brass), general buildings (tan), roads (grey), parking lots (lavender-grey), water (blue), terrain (green).
- A hand-rolled Three.js scene with a free-roam camera: **WASD** to move, **drag** to look around, **Q/E** for down/up, **shift** to boost speed, **scroll** to move forward/back. Pitch is clamped so you can never flip the view upside down.
- Click any landmark in the side panel or on the model to smoothly fly the camera to it.
- The whole page — geometry, colors, fonts, Three.js + GLTFLoader + DRACOLoader, and the Draco decoder — is base64-embedded directly into one HTML file via `site/assemble.py`, so the published page has zero external dependencies (this was a deliberate constraint: it needs to run inside strict CSPs that block any external network request, including `connect-src` restrictions that block even `blob:` URL fetches). Three.js/GLTFLoader/DRACOLoader are wired together via an import map with `data:` URIs — see `CLAUDE.md` for exactly how.

## Where this project is headed

This repo shares its data-prep pipeline with the sibling **macon-3d-print** repo (the physically-printable version), but the two are expected to diverge substantially: this one is heading toward eventually covering all of Macon rather than just the downtown core, with better building data (Overture Maps Foundation or Bibb County's own GIS, not just OSM) and toggleable stats overlays (Census ACS or similar). See `CLAUDE.md` for the current architecture and the reasoning behind it.

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

`site/three.module.js`, `GLTFLoader.js`, `DRACOLoader.js`, and `BufferGeometryUtils.js` are vendored from a pinned `three` release (unpkg) and checked in directly — no npm/bundler step needed to rebuild the page.

`data/`, `cache/`, and `output/` are gitignored (large, fully regenerable from the pipeline above).
