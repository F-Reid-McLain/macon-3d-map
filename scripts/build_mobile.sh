#!/bin/bash
# Builds a second, lower-memory variant of the model for phones, alongside
# (not replacing) the full-detail desktop build -- see CLAUDE.md's memory
# budget notes for why this exists.
#
# Round 1 (40m terrain spacing vs. desktop's 20m, demographics overlays
# still included) cut the total from ~9.6M to ~4.47M faces. A round 2
# (60m spacing + SKIP_DEMOGRAPHICS_OVERLAY=1, down to ~2.94M) was tried
# after what looked like real A/B evidence of a hard memory ceiling on an
# iPhone 13 -- but the actual repro turned out to be a stale bookmark
# pointing straight at the (undetected-device) desktop HTML, bypassing
# index.html's device check entirely (now fixed). Once that routing bug
# was fixed, the ORIGINAL round-1 build loaded fine on the same iPhone 13,
# so round 2's extra cuts were reverted back to round 1 here -- they were
# solving a problem that, per the evidence in hand, may not have actually
# been a capacity issue. If real device testing turns up an actual
# memory-ceiling crash again on the CORRECTLY-ROUTED round-1 build, redo
# round 2 (git log this file for the exact settings) rather than guessing
# at new ones.
#
# Going COARSER than the desktop's 20m is the safe direction if this needs
# revisiting -- it's the opposite of the 10m experiment that broke Draco's
# encoder outright.
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
