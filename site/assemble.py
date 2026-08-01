import base64
import json
import os

# Overridable so scripts/build_mobile.sh can produce a second, lower-memory
# HTML file (a different Draco GLB embedded) without touching the desktop
# build -- see that script and CLAUDE.md's memory-budget notes.
MODEL_GLB_PATH = os.environ.get("MODEL_GLB_PATH", "site/full_disk_draco.glb")
OUTPUT_HTML_PATH = os.environ.get("OUTPUT_HTML_PATH", "site/downtown_macon_3d.html")

LANDMARKS = [
    {"id": "gov-1", "name": "Bibb County Health Department", "category": "government", "x": 11.9, "y": 122.9, "z": 19.14},
    {"id": "gov-2", "name": "Willie C. Hill Government Center Annex", "category": "government", "x": -40.6, "y": 37.8, "z": 30.67},
    {"id": "gov-3", "name": "Terminal Station", "category": "government", "x": 7.4, "y": 5.1, "z": 20.19},
    {"id": "gov-4", "name": "Macon City Hall", "category": "government", "x": -53.4, "y": 28.2, "z": 22.57},
    {"id": "gov-5", "name": "Water Authority", "category": "government", "x": -60.4, "y": -13.4, "z": 21.65},
    {"id": "gov-6", "name": "Macon Coliseum", "category": "government", "x": 44.3, "y": 79.0, "z": 19.13},
    {"id": "gov-7", "name": "Bibb County Jail", "category": "government", "x": -89.2, "y": -32.6, "z": 22.98},
    {"id": "gov-8", "name": "Elaine H. Lucas Senior Center", "category": "government", "x": 65.2, "y": -5.6, "z": 17.88},
    {"id": "mercer-1", "name": "Jack Tarver Library", "category": "mercer", "x": -183.2, "y": -30.5, "z": 26.18},
    {"id": "mercer-2", "name": "Mercer Hall", "category": "mercer", "x": -188.9, "y": -15.3, "z": 29.64},
    {"id": "mercer-3", "name": "Willett Science Center", "category": "mercer", "x": -186.2, "y": -35.8, "z": 26.35},
    {"id": "mercer-4", "name": "Plunkett Hall", "category": "mercer", "x": -172.8, "y": -25.4, "z": 27.35},
    {"id": "mercer-5", "name": "Sherwood Hall", "category": "mercer", "x": -187.3, "y": -11.1, "z": 29.92},
    {"id": "mercer-6", "name": "Penfield Hall", "category": "mercer", "x": -179.8, "y": -24.6, "z": 26.16},
    {"id": "mercer-7", "name": "Shorter Hall", "category": "mercer", "x": -190.7, "y": -17.8, "z": 30.69},
    {"id": "mercer-8", "name": "Linden House", "category": "mercer", "x": -165.3, "y": -17.9, "z": 27.65},
    {"id": "mercer-9", "name": "Boone Hall", "category": "mercer", "x": -164.0, "y": -15.4, "z": 27.51},
    {"id": "mercer-10", "name": "Mary Erin Porter Hall", "category": "mercer", "x": -166.9, "y": -16.8, "z": 27.84},
    {"id": "mercer-11", "name": "Dowell Hall", "category": "mercer", "x": -167.3, "y": -19.8, "z": 27.82},
    {"id": "mercer-12", "name": "Walter F. George School of Law", "category": "mercer", "x": -73.2, "y": 77.7, "z": 28.47},
    {"id": "mercer-13", "name": "Legacy Hall", "category": "mercer", "x": -164.7, "y": -24.6, "z": 27.56},
    {"id": "hosp-1", "name": "Atrium Health Navicent Medical Center", "category": "medical", "x": -82.3, "y": 9.5, "z": 26.12},
    {"id": "lm-1", "name": "Fickling & Company Building", "category": "landmark", "x": -16.5, "y": 45.5, "z": 33.98},
    {"id": "lm-2", "name": "Godsey Science Center", "category": "landmark", "x": -178.0, "y": -35.1, "z": 27.76},
    {"id": "lm-3", "name": "Walker-Shinholser-Rushin House", "category": "landmark", "x": -99.9, "y": 74.3, "z": 28.91},
    {"id": "lm-4", "name": "Macon-Bibb Chamber of Commerce", "category": "landmark", "x": 23.1, "y": 94.6, "z": 19.47},

    # ---- medical (beyond the one hospital above -- clinics/hospitals found
    # via a targeted Overpass query for amenity=hospital/clinic, since the
    # original county-wide OSM fetch never targeted standalone medical POIs) ----
    {"id": "med-1", "name": "Women's Health Institute", "category": "medical", "x": -513.2, "y": 727.4, "z": 20.83},
    {"id": "med-2", "name": "Center for Ambulatory Services", "category": "medical", "x": -94.3, "y": 23.1, "z": 25.51},
    {"id": "med-3", "name": "Piedmont Macon Medical Center", "category": "medical", "x": 44.7, "y": 119.8, "z": 20.41},
    {"id": "med-4", "name": "Piedmont Macon North Hospital", "category": "medical", "x": -511.1, "y": 352.3, "z": 29.98},
    {"id": "med-5", "name": "Urology Specialists of Georgia", "category": "medical", "x": -766.5, "y": 842.3, "z": 22.83},
    {"id": "med-6", "name": "Ortho Georgia", "category": "medical", "x": -483.1, "y": 563.6, "z": 21.06},

    # ---- heritage: Ocmulgee Mounds National Historical Park. Real earthwork
    # geometry can't be reconstructed at this model's terrain resolution
    # without fabricating detail, so it gets a marker rather than volume ----
    {"id": "her-1", "name": "Ocmulgee Mounds National Historical Park", "category": "heritage", "x": 157.0, "y": 43.9, "z": 15.61},

    # ---- notable buildings ----
    {"id": "bld-1", "name": "Hay House", "category": "buildings", "x": -62.6, "y": 66.4, "z": 24.32},
    {"id": "bld-2", "name": "The Grand Opera House", "category": "buildings", "x": -24.6, "y": 43.0, "z": 20.51},
    {"id": "bld-3", "name": "Cannonball House", "category": "buildings", "x": -51.7, "y": 62.7, "z": 23.22},
    {"id": "bld-4", "name": "Sidney Lanier Cottage", "category": "buildings", "x": -85.6, "y": 43.1, "z": 27.34},
    {"id": "bld-5", "name": "Macon City Auditorium", "category": "buildings", "x": -46.2, "y": 39.8, "z": 21.52},

    # ---- notable churches ----
    {"id": "chr-1", "name": "Saint Joseph Catholic Church", "category": "church", "x": -64.6, "y": 36.2, "z": 25.32},
    {"id": "chr-2", "name": "First Presbyterian Church", "category": "church", "x": -32.9, "y": 46.6, "z": 20.44},
    {"id": "chr-3", "name": "Christ Episcopal Church", "category": "church", "x": -9.6, "y": 48.4, "z": 20.25},
    {"id": "chr-4", "name": "Mulberry Street United Methodist Church", "category": "church", "x": -32.3, "y": 59.5, "z": 21.73},
    {"id": "chr-5", "name": "Washington Avenue Presbyterian Church", "category": "church", "x": -77.1, "y": 48.9, "z": 25.65},
    {"id": "chr-6", "name": "First Baptist Church", "category": "church", "x": -69.8, "y": 29.7, "z": 24.71},
    {"id": "chr-7", "name": "Steward Chapel African Methodist Episcopal Church", "category": "church", "x": -83.2, "y": 26.9, "z": 25.56},
    {"id": "chr-8", "name": "Temple Beth Israel", "category": "church", "x": -61.2, "y": 53.8, "z": 22.87},

    # ---- music heritage ----
    {"id": "mus-1", "name": "Little Richard House and Resource Center", "category": "music", "x": -161.2, "y": 83.7, "z": 27.09},
    {"id": "mus-2", "name": "Otis Redding Foundation", "category": "music", "x": -32.4, "y": 40.4, "z": 20.73},
    {"id": "mus-3", "name": "Mercer Music at Capricorn", "category": "music", "x": -16.7, "y": -1.8, "z": 19.62},
    {"id": "mus-4", "name": "The Big House (Allman Brothers Band Museum)", "category": "music", "x": -227.3, "y": 120.2, "z": 30.55},
    {"id": "mus-5", "name": "Rose Hill Cemetery", "category": "music", "x": -59.4, "y": 132.7, "z": 21.05},
    {"id": "mus-6", "name": "The Douglass Theatre", "category": "music", "x": -5.4, "y": 22.1, "z": 19.96},
]


def b64_file(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


print("reading template...")
with open("site/template.html", "r", encoding="utf-8") as f:
    html = f.read()

print("encoding fonts...")
html = html.replace("__PUBLIC_SANS_REGULAR_B64__", b64_file("site/PublicSans-Regular.ttf"))
html = html.replace("__PUBLIC_SANS_SEMIBOLD_B64__", b64_file("site/PublicSans-SemiBold.ttf"))
html = html.replace("__PUBLIC_SANS_BOLD_B64__", b64_file("site/PublicSans-Bold.ttf"))
html = html.replace("__PLEX_MONO_B64__", b64_file("site/PlexMono-Regular.ttf"))

print("inlining Three.js core + loaders...")
html = html.replace("__THREE_MODULE_B64__", b64_file("site/three.module.js"))
html = html.replace("__BUFFER_GEOMETRY_UTILS_B64__", b64_file("site/BufferGeometryUtils.js"))
html = html.replace("__GLTF_LOADER_B64__", b64_file("site/GLTFLoader.js"))
html = html.replace("__DRACO_LOADER_B64__", b64_file("site/DRACOLoader.js"))
html = html.replace("__THREE_MESH_BVH_B64__", b64_file("site/three-mesh-bvh.js"))

print("inlining landmarks json...")
html = html.replace("__LANDMARKS_JSON__", json.dumps(LANDMARKS))

print("inlining place labels json...")
with open("output/labels.json") as f:
    LABELS = json.load(f)
html = html.replace("__LABELS_JSON__", json.dumps(LABELS))

print("inlining draco decoder files...")
html = html.replace("__DRACO_DECODER_JS_B64__", b64_file("site/draco_decoder.js"))
html = html.replace("__DRACO_WASM_WRAPPER_JS_B64__", b64_file("site/draco_wasm_wrapper.js"))
html = html.replace("__DRACO_DECODER_WASM_B64__", b64_file("site/draco_decoder.wasm"))

print(f"splicing in draco-compressed model base64 ({MODEL_GLB_PATH})...")
html = html.replace("__MODEL_DATA_B64__", b64_file(MODEL_GLB_PATH))

print(f"final html size: {len(html)/1e6:.1f} MB")
with open(OUTPUT_HTML_PATH, "w", encoding="utf-8") as f:
    f.write(html)
print(f"wrote {OUTPUT_HTML_PATH}")
