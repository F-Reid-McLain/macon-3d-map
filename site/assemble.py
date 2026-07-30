import base64
import json

LANDMARKS = [
    {"id": "gov-1", "name": "Bibb County Health Department", "category": "government", "x": 11.9, "y": 122.9, "z": 10.7},
    {"id": "gov-2", "name": "Willie C. Hill Government Center Annex", "category": "government", "x": -40.6, "y": 37.8, "z": 17.9},
    {"id": "gov-3", "name": "Terminal Station", "category": "government", "x": 7.4, "y": 5.1, "z": 12.3},
    {"id": "gov-4", "name": "Macon City Hall", "category": "government", "x": -53.4, "y": 28.2, "z": 11.4},
    {"id": "gov-5", "name": "Water Authority", "category": "government", "x": -60.4, "y": -13.4, "z": 13.2},
    {"id": "gov-6", "name": "Macon Coliseum", "category": "government", "x": 44.3, "y": 79.0, "z": 10.8},
    {"id": "gov-7", "name": "Bibb County Jail", "category": "government", "x": -89.2, "y": -32.6, "z": 14.6},
    {"id": "gov-8", "name": "Elaine H. Lucas Senior Center", "category": "government", "x": 65.2, "y": -5.6, "z": 10.0},
    {"id": "mercer-1", "name": "Jack Tarver Library", "category": "mercer", "x": -183.2, "y": -30.5, "z": 16.0},
    {"id": "mercer-2", "name": "Mercer Hall", "category": "mercer", "x": -188.9, "y": -15.3, "z": 17.0},
    {"id": "mercer-3", "name": "Willett Science Center", "category": "mercer", "x": -186.2, "y": -35.8, "z": 16.2},
    {"id": "mercer-4", "name": "Plunkett Hall", "category": "mercer", "x": -172.8, "y": -25.4, "z": 16.0},
    {"id": "mercer-5", "name": "Sherwood Hall", "category": "mercer", "x": -187.3, "y": -11.1, "z": 18.7},
    {"id": "mercer-6", "name": "Penfield Hall", "category": "mercer", "x": -179.8, "y": -24.6, "z": 16.1},
    {"id": "mercer-7", "name": "Shorter Hall", "category": "mercer", "x": -190.7, "y": -17.8, "z": 18.0},
    {"id": "mercer-8", "name": "Linden House", "category": "mercer", "x": -165.3, "y": -17.9, "z": 16.3},
    {"id": "mercer-9", "name": "Boone Hall", "category": "mercer", "x": -164.0, "y": -15.4, "z": 16.1},
    {"id": "mercer-10", "name": "Mary Erin Porter Hall", "category": "mercer", "x": -166.9, "y": -16.8, "z": 16.4},
    {"id": "mercer-11", "name": "Dowell Hall", "category": "mercer", "x": -167.3, "y": -19.8, "z": 16.4},
    {"id": "mercer-12", "name": "Walter F. George School of Law", "category": "mercer", "x": -73.2, "y": 77.7, "z": 20.6},
    {"id": "mercer-13", "name": "Legacy Hall", "category": "mercer", "x": -164.7, "y": -24.6, "z": 16.1},
    {"id": "hosp-1", "name": "Atrium Health Navicent Medical Center", "category": "hospital", "x": -82.3, "y": 9.5, "z": 13.4},
    {"id": "lm-1", "name": "Fickling & Company Building", "category": "landmark", "x": -16.5, "y": 45.5, "z": 21.3},
    {"id": "lm-2", "name": "Godsey Science Center", "category": "landmark", "x": -178.0, "y": -35.1, "z": 14.9},
    {"id": "lm-3", "name": "Walker-Shinholser-Rushin House", "category": "landmark", "x": -99.9, "y": 74.3, "z": 16.4},
    {"id": "lm-4", "name": "Macon-Bibb Chamber of Commerce", "category": "landmark", "x": 23.1, "y": 94.6, "z": 11.0},
]


def b64_file(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


print("reading template...")
with open("site/template.html", "r") as f:
    html = f.read()

print("encoding fonts...")
html = html.replace("__PUBLIC_SANS_REGULAR_B64__", b64_file("site/PublicSans-Regular.ttf"))
html = html.replace("__PUBLIC_SANS_SEMIBOLD_B64__", b64_file("site/PublicSans-SemiBold.ttf"))
html = html.replace("__PUBLIC_SANS_BOLD_B64__", b64_file("site/PublicSans-Bold.ttf"))
html = html.replace("__PLEX_MONO_B64__", b64_file("site/PlexMono-Regular.ttf"))

print("inlining model-viewer JS...")
with open("site/model-viewer.min.js", "r") as f:
    mv_js = f.read()
html = html.replace("__MODEL_VIEWER_JS__", mv_js)

print("inlining landmarks json...")
html = html.replace("__LANDMARKS_JSON__", json.dumps(LANDMARKS))

print("inlining draco decoder files...")
html = html.replace("__DRACO_DECODER_JS_B64__", b64_file("site/draco_decoder.js"))
html = html.replace("__DRACO_WASM_WRAPPER_JS_B64__", b64_file("site/draco_wasm_wrapper.js"))
html = html.replace("__DRACO_DECODER_WASM_B64__", b64_file("site/draco_decoder.wasm"))

print("splicing in draco-compressed model base64...")
html = html.replace("__MODEL_DATA_B64__", b64_file("site/full_disk_draco.glb"))

print(f"final html size: {len(html)/1e6:.1f} MB")
with open("site/downtown_macon_3d.html", "w") as f:
    f.write(html)
print("wrote site/downtown_macon_3d.html")
