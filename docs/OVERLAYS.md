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

## Demographics today (Census ACS 5-year estimates)

**What it is.** Ten present-day Census block group metrics, shown
deliberately alongside the redlining overlay above so the two can be
compared directly. Five general demographics: % Black or African American
(the exact dimension HOLC grading discriminated on, not a general "race"
composite), % with a Bachelor's degree or higher, labor force participation
rate, median household income, and homeownership rate (income and
homeownership were added beyond what was originally asked for because
they're the two most commonly-cited metrics in actual redlining-legacy
research). Plus five top-level occupation categories (the standard ACS/SOC
split: management/business/science/arts, service, sales and office, natural
resources/construction/maintenance, and production/transportation/material
moving) — added for the workforce-trends angle this project's creator
brings professionally; see `scripts/fetch_demographics.py` for exactly which
ACS table each comes from and why (the occupation categories specifically
needed the detailed table C24010, not the simpler subject table S2401 that
publishes the same split pre-computed, since subject tables don't go down to
block group in the 5-year ACS).

**Data source.** US Census Bureau ACS 5-year estimates (2022 vintage),
fetched via the public Census API (`api.census.gov`), which now requires a
free API key — instant email signup at
https://api.census.gov/data/key_signup.html, read from the `CENSUS_API_KEY`
environment variable at fetch time, never hardcoded or committed. Boundary
geometry comes from Census TIGERweb's public ArcGIS REST service (no key
needed) — same request pattern `fetch_zoning.py` already uses for Bibb
County's tax parcels, just a different host/layer. Geography is **block
group**, not tract, to sit closer to the neighborhood scale the HOLC
polygons were drawn at.

**Rendering approach — the one real departure from the redlining template.**
Redlining has 4 fixed letter grades; these are continuous values, so
`build_demographics_layers()` quantile-buckets each variable's 136 block
groups into 5 classes (roughly equal COUNTS per class, standard choropleth
practice, not equal-width value ranges that one outlier could skew) and
colors each from a 5-step sequential ColorBrewer ramp
(`DEMOGRAPHIC_COLOR_RAMPS`). Unlike redlining, all 5 buckets of one variable
merge into **one** scene node — 10 variables × 5 buckets as 50 separate
toggle rows would be unusable, so the toggle granularity is "show this
variable" not "show this specific range." `site/template.html`'s legend
renders a small 5-swatch gradient strip per row (`.ramp-swatch`) instead of
one solid color, so the range is still visible even though it's not
individually toggleable. Same float-above-buildings/translucent treatment as
redlining (`REDLINING_LIFT_MM`, and node names prefixed `demo_` are included
in the same transparency/no-shadow handling redlining already needed).

**Colors**: grey for race (deliberately neutral — encodes magnitude only, no
implied value judgment about the demographic itself), purple for education,
orange for labor force, blue for income, green for homeownership, and five
more for the occupation categories (teal, pink, gold, brown, red). Chosen to
avoid hues already load-bearing elsewhere in the legend.

## Workforce geography (Census LODES)

**What it is.** Two more block-group choropleths, same rendering approach as
demographics above: total jobs physically located in each block group, and
total employed residents living in each block group — the actual spatial
mismatch between where Macon's jobs are and where its workforce lives.

**Why not a commute-flow map.** The obvious first idea was origin-destination
lines connecting home block to work block. Tried and dropped after actually
looking at the data: 56,784 distinct block-group-to-block-group pairs touch
Bibb County, and even the top 500 by volume only account for ~15.6% of total
commuting. Real commuting here is genuinely diffuse, not concentrated into a
few dominant corridors — a "draw the biggest flows" map would be either an
unreadable tangle of thousands of lines, or a small, arbitrary-looking sample
that misrepresents how spread out it actually is. The jobs/workers density
pair is the honest version of the same underlying question, and it reuses
the exact choropleth machinery already built for demographics instead of
needing new line-geometry rendering.

**Data source.** US Census LEHD Origin-Destination Employment Statistics
(LODES8), 2022, Georgia state files — small flat CSV.GZ files (~1.5MB WAC,
~4MB RAC for the whole state, no API key needed unlike the ACS demographics
fetch): `ga_wac_S000_JT00_2022.csv.gz` (Workplace Area Characteristics, total
jobs per block) and `ga_rac_S000_JT00_2022.csv.gz` (Residence Area
Characteristics, total employed residents per block), both filtered to Bibb
County and summed up from Census block to block group. Both variables are
raw counts, not percentages, like `median_household_income` elsewhere in
this pipeline — "how many jobs/workers are physically here" is the actual
question, not a share of something.

**Code structure.** `build_commuting_layers()` and `build_demographics_layers()`
are two thin wrappers around a shared `_build_quantile_choropleth_layers()`
helper — the underlying pattern (quantile-bucket each variable, one decal per
polygon colored from its bucket, merge all buckets into one node per
variable) is identical, just over a different data source/variable list, and
this was the second copy of that exact logic, past the point where
extracting it was worth doing.

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

Known candidates for "next overlay": Macon-Bibb commissioner district
boundaries (likely on the same ArcGIS Hub `fetch_zoning.py` already found),
school district boundaries, flood zones, historic district boundaries, EPA
EJScreen environmental justice indicators, CDC PLACES neighborhood health
outcomes.
