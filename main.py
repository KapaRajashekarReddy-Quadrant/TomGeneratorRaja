import os
import json
from dotenv import load_dotenv
from blob_reader import load_metadata, extract_worksheets
from generator.dataset import generate_dataset_model
from generator.visual import generate_visual
from generator.layout import next_position
from generator.report import generate_definition, generate_item_config

# -------------------- ENV --------------------
load_dotenv()

# -------------------- PATHS --------------------
BASE_REPORT_DIR = "output/MyReport.Report"
VISUAL_DIR = f"{BASE_REPORT_DIR}/static/visuals"
DATASET_DIR = f"{BASE_REPORT_DIR}/dataset"
OUTPUT_DIR = "output"

os.makedirs(VISUAL_DIR, exist_ok=True)
os.makedirs(DATASET_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

DEFAULT_PAGE_WIDTH = 646
DEFAULT_PAGE_HEIGHT = 560

# -------------------- 1) LOAD METADATA --------------------
metadata = load_metadata()
worksheets = extract_worksheets(metadata)
if not worksheets:
    raise Exception("No worksheets found in metadata!")

# -------------------- 2) DATASET MODEL --------------------
dataset_model = generate_dataset_model(metadata)
with open(f"{DATASET_DIR}/model.json", "w", encoding="utf-8") as f:
    json.dump(dataset_model, f, indent=2)

# -------------------- 3) REPORT ROOT FILES --------------------
report_definition = generate_definition()
report_name = metadata.get("workbookName", "Auto Generated Report")
item_config = generate_item_config(report_name)

# -------------------- 4) BUILD VISUALS, GROUPED INTO PAGES --------------------
all_visuals = []
pages_by_name = {}          # page name -> {name, size, visuals: []}
page_order = []             # preserve first-seen page order

for i, ws in enumerate(worksheets):
    current_table_name = ws.get("tableName") or ws.get("table")
    if not current_table_name and ws.get("columns"):
        current_table_name = ws["columns"][0].get("table")
    if not current_table_name:
        current_table_name = "fact_sales"

    pos = next_position(i)
    z = ws.get("layout", {}).get("z", i + 1)

    visual_json = generate_visual(ws, current_table_name, pos["x"], pos["y"], z)

    # save each visual to its own file too
    visual_filename = f"visual{i+1}.json"
    with open(f"{VISUAL_DIR}/{visual_filename}", "w", encoding="utf-8") as f:
        json.dump(visual_json, f, indent=2)

    all_visuals.append(visual_json)

    page_name = ws.get("page") or ws.get("dashboard") or "Page 1"
    if page_name not in pages_by_name:
        page_size = ws.get("pageSize") or {
            "width": DEFAULT_PAGE_WIDTH,
            "height": DEFAULT_PAGE_HEIGHT,
        }
        pages_by_name[page_name] = {
            "name": page_name,
            "size": page_size,
            "visuals": [],
        }
        page_order.append(page_name)
    pages_by_name[page_name]["visuals"].append(visual_json)

pages = [pages_by_name[name] for name in page_order]

dashboards = [
    {
        "name": p["name"],
        "width": p["size"]["width"],
        "height": p["size"]["height"],
    }
    for p in pages
]

report_definition["pages"] = pages

# -------------------- 5) SAVE REPORT ROOT FILES --------------------
with open(f"{BASE_REPORT_DIR}/definition.pbir", "w", encoding="utf-8") as f:
    json.dump(report_definition, f, indent=2)

with open(f"{BASE_REPORT_DIR}/item.config.json", "w", encoding="utf-8") as f:
    json.dump(item_config, f, indent=2)

# -------------------- 6) SAVE RUNTIME OUTPUT (target schema) --------------------
runtime_visuals = {
    "visuals": all_visuals,
    "pages": pages,
    "dashboards": dashboards,
}

with open("output/runtime_visuals.json", "w", encoding="utf-8") as f:
    json.dump(runtime_visuals, f, indent=2)

print(f"PBIR project generated: {len(all_visuals)} visual(s) across {len(pages)} page(s).")
