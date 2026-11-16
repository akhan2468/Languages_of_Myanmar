# prepare_data.py
# Data processing for the "Languages of Myanmar" dashboard.
#
# Input (downloaded by hand into the raw/ folder):
#   raw/languages.csv   - Glottolog 5 language list   (github.com/glottolog/glottolog-cldf, cldf folder)
#   raw/values.csv      - Glottolog 5 values: endangerment, documentation, family tree
#   raw/ne_10m_admin_1_states_provinces.geojson - Natural Earth state/region borders
#   scripts_filled.csv  - my own table: script + written/oral for 23 major languages
#
# Output (used by index.html):
#   languages.json      - one record per language (like coordinates.json in the weather example)
#   data/states.geojson - Myanmar's 14 states/regions for the map
#   data/scripts.json   - my script table as JSON
#
# Run:  pip install shapely   then   python prepare_data.py

import csv
import json
import os
from shapely.geometry import shape, mapping, Point

# ---------- Step 1: read Glottolog ----------
languages = {}
for row in csv.DictReader(open("raw/languages.csv", encoding="utf-8")):
    languages[row["ID"]] = row

# values.csv has many rows per language. Keep only the 3 things I need.
#   aes = endangerment level (1 = not endangered ... 6 = extinct)
#   med = best documentation (0 = long grammar ... 4 = wordlist or less)
#   classification = family tree path, e.g. "sino1245/kuki1246/..."
values = {}
for row in csv.DictReader(open("raw/values.csv", encoding="utf-8")):
    if row["Parameter_ID"] in ("aes", "med", "classification", "category"):
        values.setdefault(row["Language_ID"], {})[row["Parameter_ID"]] = row["Value"]

STATUS = {"1": "Not endangered", "2": "Threatened", "3": "Shifting",
          "4": "Moribund", "5": "Nearly extinct", "6": "Extinct"}
DOCS = {"0": "Long grammar", "1": "Grammar", "2": "Grammar sketch",
        "3": "Texts / phonology", "4": "Wordlist or less"}

# Glottolog's branch names are technical, so I give each big branch a readable group name.
GROUP_NAMES = {
    "Kuki-Chin-Naga": "Chin & Naga",
    "Burmo-Qiangic": "Burmish & Lolo",
    "Karenic": "Karen",
    "Brahmaputran": "Kachin (Jingpho)",
    "Khasi-Palaung": "Palaung & Wa",
    "Kam-Tai": "Tai (Shan)",
}

# ---------- Step 2: state/region borders ----------
states = []
features = []
borders = json.load(open("raw/ne_10m_admin_1_states_provinces.geojson", encoding="utf-8"))
for f in borders["features"]:
    if f["properties"]["adm0_a3"] != "MMR":
        continue
    geom = shape(f["geometry"]).simplify(0.01)          # make the file smaller
    name = f["properties"]["name"]
    states.append((name, geom))
    features.append({"type": "Feature", "properties": {"name": name}, "geometry": mapping(geom)})

os.makedirs("data", exist_ok=True)
json.dump({"type": "FeatureCollection", "features": features},
          open("data/states.geojson", "w", encoding="utf-8"))


def find_state(lon, lat):
    """Return the state/region that contains this point, or 'Cross-border'."""
    point = Point(lon, lat)
    for name, geom in states:
        if geom.contains(point):
            return name
    # Points just outside a border (within ~30 km) still count for the nearest state.
    nearest = min(states, key=lambda s: s[1].distance(point))
    if nearest[1].distance(point) < 0.3:
        return nearest[0]
    return "Cross-border"


# ---------- Step 3: filter and clean ----------
SKIP = ("Sign Language", "Bookkeeping", "Unattested", "Pidgin", "Unclassifiable", "Artificial Language")
result = []
for lid, row in languages.items():
    # only real languages that Glottolog lists for Myanmar (country code MM)
    if row["Level"] != "language" or "MM" not in row["Countries"].split(";"):
        continue
    if row["Latitude"] == "":
        continue
    v = values.get(lid, {})
    if v.get("category") in SKIP or row["Name"] == "Old Burmese":
        continue
    lat = float(row["Latitude"])
    lon = float(row["Longitude"])
    # drop points far away (e.g. Mandarin is placed in Beijing)
    if not (86 <= lon <= 106 and 5 <= lat <= 31):
        continue
    # Glottolog puts Burmese on the Chin border. I move it to central Myanmar (Mandalay).
    if row["Name"] == "Burmese":
        lat, lon = 21.6, 95.6
    # Falam Chin and Maru are important Myanmar languages, but Glottolog puts their point
    # just across the border. I move them inside Chin State (Falam town) and Kachin State.
    if row["Name"] == "Falam Chin":
        lat, lon = 22.91, 93.68
    if row["Name"] == "Maru":
        lat, lon = 25.6, 98.0
    # Languages whose point is outside Myanmar are mostly spoken in a neighbouring country, so I leave them out.
    if find_state(lon, lat) == "Cross-border":
        continue

    tree = [languages[x]["Name"] for x in v.get("classification", "").split("/") if x in languages]
    family = tree[0] if tree else "Isolate"
    if family == "Sign Language":      # sign languages have no spoken/written script, so leave them out
        continue
    branch = tree[1] if len(tree) > 1 else family

    result.append({
        "name": row["Name"],
        "glottocode": lid,
        "lat": round(lat, 4),
        "lon": round(lon, 4),
        "family": family,
        "branch": branch,
        "group": GROUP_NAMES.get(branch, "Other"),
        "state": find_state(lon, lat),
        "status": STATUS.get(v.get("aes"), "Unknown"),
        "docs": DOCS.get(v.get("med"), "Unknown"),
        "countries": row["Countries"].split(";"),
    })

json.dump(result, open("languages.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("Saved", len(result), "languages")

# ---------- Step 3b: count languages per state (for the bar chart) ----------
counts = {}
for lang in result:
    if lang["state"] == "Cross-border":      # not inside a Myanmar state, so not in the bar chart
        continue
    counts[lang["state"]] = counts.get(lang["state"], 0) + 1

state_counts = []
for state in counts:
    state_counts.append({"STATE": state, "COUNT": counts[state]})
state_counts.sort(key=lambda row: row["COUNT"], reverse=True)    # most languages first

json.dump(state_counts, open("data/state_counts.json", "w", encoding="utf-8"), indent=1)
print("Saved", len(state_counts), "state counts")

# ---------- Step 4: my script table ----------
if os.path.exists("scripts_filled.csv"):
    scripts = []
    for row in csv.DictReader(open("scripts_filled.csv", encoding="utf-8-sig")):
        if row["script"].strip() == "":
            continue
        scripts.append({
            "name": row["language"].strip(),
            "group": GROUP_NAMES.get(row["language_group"].strip(), "Other"),
            "script": row["script"].strip(),
            "written": row["written_or_oral"].strip(),
            "source": row["source_link"].strip(),
        })
    json.dump(scripts, open("data/scripts.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("Saved", len(scripts), "script records")
