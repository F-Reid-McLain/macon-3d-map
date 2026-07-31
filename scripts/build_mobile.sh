#!/bin/bash
# Builds a second, lower-memory variant of the model for phones, alongside
# (not replacing) the full-detail desktop build -- see CLAUDE.md's memory
# budget notes for why this exists (iOS Safari repeatedly crashing/reloading
# the page, most likely from exceeding its per-tab memory ceiling with the
# desktop build's ~9.6M faces).
#
# Only lever pulled so far is DEM_SAMPLE_SPACING_M (terrain is 7.03M of the
# ~9.6M total faces -- by far the dominant cost), doubled from the desktop's
# 20m to 40m. This is a FIRST ATTEMPT, not a verified fix -- it needs to
# actually be tested on a real phone. If it still crashes, the next lever is
# probably simplifying/dropping small buildings (residential is the next
# largest category at 1.2M faces), not coarsening terrain further, since
# terrain quality (esp. the river bluff) is a big part of the point of this
# model. Going COARSER than the desktop's 20m is the safe direction -- it's
# the opposite of the 10m experiment that broke Draco's encoder outright.
#
# Run from the project root: `bash scripts/build_mobile.sh`
set -euo pipefail

export DEM_SAMPLE_SPACING_M=40.0
export OUTPUT_GLB_PATH=output/colored/full_disk_colored_mobile.glb

echo "building mobile-variant model (DEM_SAMPLE_SPACING_M=$DEM_SAMPLE_SPACING_M) ..."
python3 scripts/build_colored_disk.py

echo "compressing ..."
npx gltf-pipeline -i "$OUTPUT_GLB_PATH" -o site/full_disk_draco_mobile.glb -d \
  --draco.compressionLevel=10 --draco.quantizePositionBits=14 \
  --draco.quantizeColorBits=8 --draco.unifiedQuantization

echo "assembling ..."
MODEL_GLB_PATH=site/full_disk_draco_mobile.glb OUTPUT_HTML_PATH=site/downtown_macon_3d_mobile.html python3 site/assemble.py

echo "done -- site/downtown_macon_3d_mobile.html"
