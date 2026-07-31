# Data overlays

The site can lay historical or statistical data on top of the base relief
map as a **toggleable layer** — distinct from the base map's own building/
road/water/terrain categories, which are what the place is built of.
Overlays are what gets shown *about* the place: they can be turned off
entirely and the map still makes complete sense underneath.

The first overlay is 1930s HOLC redlining grades (below). It's meant as the
template for whatever comes next — school district boundaries, Census ACS
demographics, flood zones, historic district boundaries, whatever the next
"show X on the map" idea turns out to be.

## Redlining (1938 HOLC survey)

**What it is.** In the 1930s the federal Home Owners' Loan Corporation
graded US neighborhoods A ("Best") through D ("Hazardous") to guide mortgage
lending risk. The grading criteria were explicitly racial and ethnic, not
just economic — a "D" grade routinely cited "negro concentration" or
"infiltration of a lower grade population" as the reason, regardless of the
area's actual home values or housing quality. Banks then used these grades
for decades to deny mortgages and insurance in "redlined" (D-graded) areas,
a major, well-documented driver of the racial wealth gap and residential
segregation that persists in American cities today. Macon was one of the
most severely redlined cities in the country — the majority of the surveyed
city was graded C or D.

**Data source.** University of Richmond's [Mapping Inequality: Redlining in
New Deal America](https://dsl.richmond.edu/panorama/redlining/) project
(Digital Scholarship Lab, with Richard Marciano, Nathan Connolly, LaDale
Winling and others), accessed via a public GeoParquet mirror on
[Source Cooperative](https://source.coop/repositories/cboettig/mappinginequality)
(`data.source.coop/cboettig/mappinginequality/mappinginequality.parquet`) —
the project's own `dsl.richmond.edu` download links now only serve their SPA
shell, not raw data, so the mirror is the actually-usable path in.

**License and required citation.** CC BY-NC-SA 4.0 (non-commercial,
share-alike, attribution required). Cite as:

> Robert K. Nelson, LaDale Winling, Richard Marciano, Nathan Connolly, et al.,
> "Mapping Inequality," *American Panorama*, ed. Robert K. Nelson and
> Edward L. Ayers, accessed [DATE], https://dsl.richmond.edu/panorama/redlining/

This citation is shown in-app, in the legend panel, directly under the
redlining section's rows (see `site/template.html`'s `LEGEND_SECTIONS`
entry for `"Historical redlining (1938 HOLC survey)"`).

**Pipeline.** `scripts/fetch_redlining.py`:
1. Downloads the parquet to a local temp file (`geopandas.read_parquet()`
   can't read an `https://` URL directly — no pyarrow filesystem is
   registered for plain HTTPS — so download-then-read, same pattern as
   every other `fetch_*.py` script's plain `requests.get()`).
2. Filters to `city == "Macon", state == "GA"` (41 polygons).
3. Drops the one ungraded "Industrial and Commercial" polygon (HOLC graded
   those by land use, not creditworthiness — a different thing than
   redlining, and out of scope for this layer). 40 graded A/B/C/D polygons
   remain (2 A, 6 B, 16 C, 16 D).
4. Reprojects to EPSG:4326 and writes `data/redlining_raw.geojson`.

Needs `pyarrow` (geopandas' parquet reader) — not otherwise a project
dependency, since nothing else here touches (geo)parquet.

**Rendering approach.** `build_colored_disk.py`'s `build_redlining_layer()`
reprojects the 40 polygons to the model's UTM/model-space, and builds one
thin extruded decal mesh per grade (same decal technique as roads/water/
parking — see `CLAUDE.md`'s "Legend toggles" section) — but lifted **25mm**
above the terrain (`REDLINING_LIFT_MM`, vs. the ~0.03mm lift used for
road/water/parking decals) so it visibly floats above rooftops rather than
sitting flush with the ground. This is not tiled — 40 polygons across the
whole disk is cheap enough to build once, unlike the 97-tile terrain/
building pipeline.

Each grade gets its own top-level Scene node (`redlining_a`/`_b`/`_c`/`_d`,
appended to `CATEGORIES`), so it plugs into the existing multi-node legend
toggle system with no special-casing there. In `site/template.html`, any
mesh whose name starts with `redlining_` additionally gets
`material.transparent = true` and `opacity = 0.5` (plus `depthWrite = false`
to avoid transparency sorting artifacts, and `castShadow = false`, since a
translucent floating decal casting a hard shadow on the buildings below
would look wrong) — this is what makes it read as *an overlay laid on top
of* today's map, not a replacement for it.

**Colors** (`REDLINING_COLORS` in `build_colored_disk.py`, matching the
grading scheme's traditional color coding): A = green, B = blue,
C = yellow, D = red. Kept distinct from every other color already in use
elsewhere in the legend (zoning, hospitals, etc.) so there's no visual
collision when overlays and base-map categories are on screen together.

## Adding the next overlay

The redlining layer is the template to copy:

1. A `scripts/fetch_<name>.py` that fetches/filters source data down to
   just Macon/Bibb County, writes a `data/<name>_raw.geojson` (gitignored,
   like everything else in `data/`).
2. A `build_<name>_layer()` function in `build_colored_disk.py` that
   reprojects to model space and returns `{category_name: mesh}` — reuse
   the decal-prism pattern (`extrude_polygon` + lift) unless the data calls
   for something else (e.g. a line-based overlay might want a tube/ribbon
   instead of a filled decal).
3. Append the new category name(s) to `CATEGORIES`.
4. Add a `LEGEND_SECTIONS` entry in `site/template.html` with a `heading`,
   `rows` (one per sub-category/grade), and a `note` (attribution + a
   sentence or two of context for a general audience — required if the
   source data has a citation requirement, worth doing anyway even if not).
5. If the overlay should float above buildings rather than sit flush with
   terrain, give it its own lift constant and add its node-name prefix to
   the `transparent`/`opacity` handling in the `gltfLoader.parse()` callback
   (currently keyed on `obj.name.startsWith("redlining_")` — generalize this
   check, or add a second prefix, once a second floating overlay exists).
6. Rebuild: re-run `build_colored_disk.py`, re-run `gltf-pipeline` (Draco
   compress), re-run `site/assemble.py`. Verify with Playwright against a
   real-CSP local server (see `CLAUDE.md`) before publishing.

Known candidates for "next overlay": school district boundaries, Census ACS
demographic data (income, race, etc. — useful alongside redlining, to show
how closely today's patterns still track the 1930s grades), flood zones,
historic district boundaries.
