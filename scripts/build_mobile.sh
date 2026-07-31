#!/bin/bash
# Builds a second, lower-memory variant of the model for phones, alongside
# (not replacing) the full-detail desktop build -- see CLAUDE.md's memory
# budget notes for why this exists (iOS Safari repeatedly crashing/reloading
# the page, consistent with exceeding its per-tab memory ceiling with the
# desktop build's ~9.6M faces).
#
# Round 1 (40m terrain spacing, demographics overlays included) cut the
# total from ~9.6M to ~4.47M faces and was NOT enough on its own -- real A/B
# evidence from two actual devices on the same round-1 build: an iPhone 13
# (4GB RAM) still crashed, an iPhone 15 (6GB RAM) loaded fine. Since Safari
# exposes no way to feature-detect device RAM (navigator.deviceMemory isn't
# supported at all), the only lever is making the ONE mobile build lighter
# across the board -- this helps the 13 without hurting the 15, which
# already had headroom to spare.
#
# Round 2, two more cuts:
#   - SKIP_DEMOGRAPHICS_OVERLAY=1: these default to HIDDEN (see
#     site/template.html's `defaultOff: true`), but Three.js keeps hidden
#     geometry fully GPU-resident regardless -- ~582K faces (13% of the
#     round-1 mobile total) for zero benefit on first load. Dropped entirely
#     from this build rather than just left invisible; a mobile visitor
#     loses the ability to toggle them on, which is a real but much smaller
#     cost than the crash it's trading against.
#   - DEM_SAMPLE_SPACING_M 40m -> 60m: terrain was still the largest single
#     category even after round 1's cut (1.9M of 4.47M faces).
#
# If THIS still isn't enough on a 4GB device, the next lever is probably
# simplifying/dropping small buildings (residential is the next-largest
# category at 1.2M faces) rather than coarsening terrain further still,
# since terrain/bluff detail is a real part of the point of this model.
# Going COARSER than the desktop's 20m is the safe direction either way --
# it's the opposite of the 10m experiment that broke Draco's encoder
# outright.
#
# Run from the project root: `bash scripts/build_mobile.sh`
set -euo pipefail

export DEM_SAMPLE_SPACING_M=60.0
export SKIP_DEMOGRAPHICS_OVERLAY=1
export OUTPUT_GLB_PATH=output/colored/full_disk_colored_mobile.glb

echo "building mobile-variant model (DEM_SAMPLE_SPACING_M=$DEM_SAMPLE_SPACING_M, SKIP_DEMOGRAPHICS_OVERLAY=$SKIP_DEMOGRAPHICS_OVERLAY) ..."
python3 scripts/build_colored_disk.py

echo "compressing ..."
npx gltf-pipeline -i "$OUTPUT_GLB_PATH" -o site/full_disk_draco_mobile.glb -d \
  --draco.compressionLevel=10 --draco.quantizePositionBits=14 \
  --draco.quantizeColorBits=8 --draco.unifiedQuantization

echo "assembling ..."
MODEL_GLB_PATH=site/full_disk_draco_mobile.glb OUTPUT_HTML_PATH=site/downtown_macon_3d_mobile.html python3 site/assemble.py

echo "done -- site/downtown_macon_3d_mobile.html"
