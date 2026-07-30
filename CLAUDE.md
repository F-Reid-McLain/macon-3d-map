# CLAUDE.md

Guidance for working in this repo.

## What this project is, and where it's going

An interactive 3D relief map of downtown Macon, currently built on Google's `<model-viewer>` web component and shipped as one self-contained HTML file (see `site/assemble.py`). It shares its data-prep pipeline with the sibling `macon-3d-print` repo (physically-printable STLs), but the two are expected to diverge — this repo is mid-transition toward:

- A hand-rolled Three.js scene replacing `<model-viewer>`, specifically to support a free-roam camera (`<model-viewer>`'s camera is orbit-only — look-at-target + distance + two angles — with no way to translate through space, which is a dead end for "drive around the city").
- Eventually covering all of Macon, not just the downtown disk, with better building data (Overture Maps Foundation or Bibb County's own GIS, not just OSM) and toggleable stats overlays (Census ACS or similar).
- A full WASM game engine (e.g. Godot) was considered and explicitly rejected for now: its footprint (tens of MB before content) blows past what a self-contained single HTML file can reasonably hold, and it would badly hurt the Playwright-based screenshot/raycast debugging loop this project leans on heavily (see below). Worth revisiting only if this ever moves off the self-contained-single-file model entirely.

## Hard-won constraints — don't relearn these the hard way

**The page must be one self-contained HTML file with zero external network calls.** This was originally driven by publishing to a CSP-locked hosting environment (`connect-src 'self'`), which blocks not just cross-origin fetches but `fetch()` on `blob:` URLs too. Concretely:

- Every asset (fonts, the 3D library, the Draco decoder, the model itself) is base64-embedded and served via a patched `window.fetch()` that intercepts specific sentinel filenames/paths and answers from memory — see the `LOCAL_ASSETS` map and fetch-patching IIFE near the top of `site/template.html`'s scripts. If you add a new binary dependency, follow this exact pattern rather than inventing a new one.
- A `<script type="module">` is required for any ESM-format library (e.g. `model-viewer.min.js` ends in `export{...}`) — a classic `<script>` tag fails to parse `export` syntax silently in a way that looks like nothing loaded at all (zero progress events, no errors) rather than a clear syntax error.
- Whatever replaces `<model-viewer>` (per the Three.js migration) needs to keep this constraint: vendor Three.js/GLTFLoader/DRACOLoader as embedded base64 + an import map, not a CDN `<script src>`.

## The axis-convention trap (already debugged once — do it right this time)

`<model-viewer>`'s `orientation="-90deg 0deg 0deg"` attribute (needed because the mesh is authored Z-up, glTF/model-viewer defaults to Y-up) turned out to require a manual `(x, z, -y)` swap for `camera-target`/`camera-orbit`, but *not* for hotspot `data-position` (which takes the raw authored `(x, y, z)` directly) — two different, undocumented conventions for what looks like the same coordinate space. This took an extremely long debugging session to pin down, using `model-viewer`'s `positionAndNormalFromPoint()` API to get real raycast ground-truth rather than trusting visual impressions (color-matching a rendered screenshot turned out to be an unreliable signal — lighting/anti-aliasing produced false positives more than once).

When the Three.js migration happens, **avoid this whole class of bug by construction**: apply the `-90° X` rotation once to the loaded model's root `Group`, then parent hotspot markers as `Object3D` children of that *same* rotated group using their raw authored coordinates directly (the scene graph handles the rotation for you — no manual swap, ever). For the camera (which isn't a child of that group), convert a landmark's local coordinate to world space with `group.localToWorld(...)`, not hand-derived matrix math.

## Debugging approach that actually works here

Visual screenshots alone are not reliable for verifying 3D alignment — small buildings can be a handful of pixels, and color-threshold matching produces false positives under directional lighting. What worked:

- Serve the built HTML locally (`python3 -m http.server`) and drive it with Playwright.
- Use numeric ground-truth checks, not just screenshots: raycasting via a `positionAndNormalFromPoint()`-equivalent API against a *geometrically unambiguous* reference (this project used the model's own circular edge — a known, exact radius — to pin down which coordinate slots meant what, since color-matching a specific building repeatedly gave false signals).
- If you add a hotspot/camera feature and it "looks kind of right," don't trust it — get the exact numeric hit-test before believing it's correct. This bit us more than once earlier in this project's life.

## Data pipeline

Same chain as `macon-3d-print`: `fetch_osm.py -> parse_osm.py -> filter_ms_footprints.py -> merge_footprints.py -> assign_zones.py`, but the terminal step here is `build_colored_disk.py` (not `build_grid.py`'s plain STL export) — it imports `build_grid.py` directly for shared terrain/geometry logic, so keep both together in `scripts/`. Roads in this (web-only, non-printed) version should render flush with the terrain rather than grooved — printing constraints don't apply here.

`data/`, `cache/`, and `output/` are gitignored (large, regenerable).
