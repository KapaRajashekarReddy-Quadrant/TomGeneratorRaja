# generator/visual.py
"""
Tableau -> Power BI visual generation.

Loads the Tableau->PowerBI chart-type mapping from a local JSON file
(mapping/StandardMapping_Tableau_to_PowerBi.json) instead of a remote
Google Sheet, and emits visuals in the "rich" schema:

{
  "visualType": "...",
  "title": "...",
  "layout": {"x", "y", "width", "height", "z"},
  "bindings": {
      "Category": {"table", "column"},          # optional
      "X": {...}, "Y": [{"table","column"|"measure","aggregation"}]  # per chart family
  },
  "sortBy": {"target": {...}, "direction": "Ascending"|"Descending"}, # optional
  "filters": [{"table","column","operator","values"}],                # optional
  "properties": [{"objectName","propertyName","value"}]               # optional
}
"""

import json
import os

_MAPPING_CACHE = None

_DEFAULT_MAPPING_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "mapping",
    "StandardMapping_Tableau_to_PowerBi.json",
)


def get_mapping_dictionary(mapping_path: str = _DEFAULT_MAPPING_PATH) -> dict:
    """
    Loads the Tableau -> Power BI visual-type mapping from the local
    StandardMapping_Tableau_to_PowerBi.json file and caches it.
    """
    global _MAPPING_CACHE

    if _MAPPING_CACHE is not None:
        return _MAPPING_CACHE

    try:
        with open(mapping_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        # normalize keys to lowercase/stripped for lookup
        _MAPPING_CACHE = {k.strip().lower(): v for k, v in raw.items()}
        print(f"Visual mapping loaded from {mapping_path} ({len(_MAPPING_CACHE)} entries)")
        return _MAPPING_CACHE
    except Exception as e:
        print(f"Failed to load local mapping file ({mapping_path}): {e}")
        # minimal built-in fallback so the pipeline never hard-fails
        _MAPPING_CACHE = {
            "text table": "tableEx",
            "standard bar": "clusteredBarChart",
            "standard column": "clusteredColumnChart",
            "line chart": "lineChart",
            "pie chart": "pieChart",
        }
        return _MAPPING_CACHE


def _map_visual_type(tableau_type: str, mapping: dict) -> str:
    key = (tableau_type or "").strip().lower()
    mapped = mapping.get(key)
    if mapped is None:
        # either not found, or explicitly null in the mapping table
        # (e.g. "azure maps visual", "isochrone map") -> safe fallback
        return "tableEx"
    return mapped


def _measure_entry(m: dict, table_name: str) -> dict:
    """Build one entry of a bindings['Y'] array from a source measure dict."""
    entry = {}
    entry["table"] = m.get("table", table_name)
    if "measure" in m:
        entry["measure"] = m["measure"]
    else:
        entry["column"] = m.get("column")
    if m.get("aggregation"):
        entry["aggregation"] = m["aggregation"]
    return entry


def generate_visual(ws: dict, table_name: str, x: int, y: int, z: int = 1) -> dict:
    """
    Generate a single Power BI visual definition (rich schema) from a
    normalized Tableau worksheet dict.

    Expected (flexible) worksheet shape:
        {
          "name": str,
          "visualType" | "type" | "chartType" | "vizType": str  (Tableau chart name),
          "layout": {"x","y","width","height","z"}   # optional, overrides x/y/z args
          "category": {"table","column"}              # optional
          "x_field": {"table","column"}                # optional, for X/Y axis charts
          "measures" | "values": [ {"table","column"|"measure","aggregation"} ],
          "sortBy": {"target": {...}, "direction": "Ascending"|"Descending"},  # optional
          "filters": [ {"table","column","operator","values"} ],              # optional
          "properties": [ {"objectName","propertyName","value"} ],            # optional
        }
    """
    mapping = get_mapping_dictionary()

    tableau_type = (
        ws.get("visualType")
        or ws.get("type")
        or ws.get("chartType")
        or ws.get("vizType")
        or "text table"
    )
    visual_type = _map_visual_type(tableau_type, mapping)

    layout_in = ws.get("layout", {})
    layout = {
        "x": layout_in.get("x", x),
        "y": layout_in.get("y", y),
        "width": layout_in.get("width", 500),
        "height": layout_in.get("height", 300),
        "z": layout_in.get("z", z),
    }

    category = ws.get("category")
    x_field = ws.get("x_field") or ws.get("xField")
    measures = ws.get("measures") or ws.get("values") or []

    bindings = {}

    if category:
        bindings["Category"] = {
            "table": category.get("table", table_name),
            "column": category.get("column"),
        }
    if x_field:
        bindings["X"] = {
            "table": x_field.get("table", table_name),
            "column": x_field.get("column"),
        }
    if measures:
        bindings["Y"] = [_measure_entry(m, table_name) for m in measures]

    if not bindings:
        # fallback: dump raw columns as a plain values list (basic table)
        columns = ws.get("columns", []) or []
        bindings["Y"] = [
            {"table": c.get("table", table_name), "column": c.get("column")}
            for c in columns
        ]

    visual = {
        "visualType": visual_type,
        "title": ws.get("name", "Auto Visual"),
        "layout": layout,
        "bindings": bindings,
    }

    if ws.get("sortBy"):
        visual["sortBy"] = ws["sortBy"]
    if ws.get("filters"):
        visual["filters"] = ws["filters"]
    if ws.get("properties"):
        visual["properties"] = ws["properties"]

    return visual
