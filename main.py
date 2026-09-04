# import os
# import re
# import json
# import zipfile
# import tempfile
# import xml.etree.ElementTree as ET
# from typing import List, Optional, Literal
# from openai import OpenAI
# from tableauhyperapi import HyperProcess, Connection, Telemetry
# from dotenv import load_dotenv
# from azure.storage.blob import BlobServiceClient
# from pydantic import BaseModel, Field

# from fastapi import FastAPI, HTTPException
# from fastapi.middleware.cors import CORSMiddleware

# app = FastAPI()

# # ============================================================
# # CORS CONFIGURATION
# # ============================================================

# origins = [
#     "https://id-preview--1115fb10-6ea8-4052-8d1b-31238016c02e.lovable.app",
#     "https://reportmigration-frontend-g9ceape5ddgxa5gq.eastus-01.azurewebsites.net",
# ]

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=origins,
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# # ============================================================
# # LOAD ENV VARIABLES
# # ============================================================

# load_dotenv()

# OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# TWBX_CONTAINER = os.getenv("TWBX_CONTAINER")
# AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")

# if not OPENAI_API_KEY:
#     raise ValueError("OPENAI_API_KEY not set in .env")

# if not TWBX_CONTAINER:
#     raise ValueError("TWBX_CONTAINER not set in .env")

# if not AZURE_STORAGE_CONNECTION_STRING:
#     raise ValueError("AZURE_STORAGE_CONNECTION_STRING not set in .env")

# # ============================================================
# # PYDANTIC SCHEMAS FOR TABULAR / FABRIC (modelSchema)
# # ============================================================

# ColumnDataType = Literal["string", "int64", "double", "dateTime", "boolean", "decimal"]
# MeasureDataType = Literal["int64", "double", "string", "dateTime", "boolean", "decimal"]


# class ColumnSchema(BaseModel):
#     name: str
#     type: ColumnDataType
#     isHidden: Optional[bool] = False


# class MeasureSchema(BaseModel):
#     name: str
#     expression: str
#     dataType: MeasureDataType = "double"
#     role: str = "measure"
#     defaultFormat: Optional[str] = Field(
#         default=None,
#         description="Standard DAX format string, e.g., '0.00%', '#,0', '$#,##0.00', or None",
#     )


# class TableSchema(BaseModel):
#     name: str
#     is_physical: bool = True
#     columns: List[ColumnSchema]
#     measures: Optional[List[MeasureSchema]] = None


# class RelationshipSchema(BaseModel):
#     name: str
#     from_table: str
#     from_col: str
#     to_table: str
#     to_col: str


# class SemanticModelSchema(BaseModel):
#     model_name: str
#     tables: List[TableSchema]
#     relationships: List[RelationshipSchema]

# class KpiSuggestion(BaseModel):
#     """Duplicate-KPI recommendations from pre-migration analysis."""
#     remap: dict[str, str] = Field(
#         default_factory=dict,
#         description="removed KPI name -> keep KPI name",
#     )
#     remove: list[str] = Field(
#         default_factory=list,
#         description="KPI names that must not become measures",
#     )

# def apply_kpi_suggestions_to_measures(
#     measures: list[dict],
#     suggestions: "KpiSuggestion | None",
# ) -> list[dict]:
#     """Drop recommended_remove measures; rewrite DAX refs to recommended_keep."""
#     if not suggestions:
#         return measures

#     remove_l = {n.strip().lower() for n in (suggestions.remove or []) if n and n.strip()}
#     remap_l = {
#         k.strip().lower(): v.strip()
#         for k, v in (suggestions.remap or {}).items()
#         if k and v and k.strip() and v.strip()
#     }
#     remove_l |= set(remap_l.keys())

#     kept = []
#     for m in measures:
#         name = (m.get("name") or "").strip()
#         if not name or name.lower() in remove_l:
#             continue
#         kept.append(dict(m))

#     def rewrite_expr(expr: str) -> str:
#         if not expr:
#             return expr
#         out = expr
#         for old, new in sorted(remap_l.items(), key=lambda kv: -len(kv[0])):
#             out = re.sub(
#                 rf"\[{re.escape(old)}\]",
#                 f"[{new}]",
#                 out,
#                 flags=re.IGNORECASE,
#             )
#         return out

#     for m in kept:
#         if isinstance(m.get("expression"), str):
#             m["expression"] = rewrite_expr(m["expression"])
#     return kept


# # ============================================================
# # AZURE BLOB DOWNLOAD
# # ============================================================

# def download_twbx_from_container(folder_name: str):
#     blob_service_client = BlobServiceClient.from_connection_string(
#         AZURE_STORAGE_CONNECTION_STRING
#     )
#     container_client = blob_service_client.get_container_client(TWBX_CONTAINER)
#     blobs = container_client.list_blobs(name_starts_with=folder_name)

#     for blob in blobs:
#         if blob.name.lower().endswith(".twbx"):
#             local_path = os.path.join(
#                 tempfile.gettempdir(),
#                 os.path.basename(blob.name)
#             )

#             with open(local_path, "wb") as f:
#                 download_stream = container_client.download_blob(blob.name)
#                 f.write(download_stream.readall())

#             print(f"Downloaded: {blob.name}")
#             return local_path

#     raise FileNotFoundError("No .twbx file found in specified folder.")


# # ============================================================
# # UTILS & SANITIZERS
# # ============================================================

# def strip_ns(root: ET.Element):
#     for el in root.iter():
#         if "}" in el.tag:
#             el.tag = el.tag.split("}", 1)[1]


# def clean(val: str) -> str:
#     if not val:
#         return ""
#     return re.sub(r'[\[\]"]', "", val).strip()


# def normalize_table_name(name: str) -> str:
#     name = clean(name)
#     name = re.sub(r"\s*\(.*?\)", "", name)
#     name = re.sub(r"[_\-]?[0-9a-fA-F]{32}", "", name)
#     name = re.sub(r"\.(csv|txt|xlsx|xls|hyper|tde)", "", name, flags=re.IGNORECASE)
#     name = re.sub(r'^Extract[_\s]?', '', name, flags=re.IGNORECASE)
#     name = name.split("#")[0]
#     name = re.sub(r"[^a-zA-Z0-9 _-]", "", name).strip()
#     return name


# def is_junk_table(name: str) -> bool:
#     name = name.lower()
#     return name.startswith("federated") or name in ["clipboard", "csv"]


# def dax_identifier(table: str, column: str) -> str:
#     return f"'{table}'[{column}]"


# def dax_type_from_tableau(local_type: str) -> ColumnDataType:
#     """Convert Tableau datatype to valid Tabular / TOM DataType."""
#     normalized = (local_type or "").strip().lower()

#     mapping: dict[str, ColumnDataType] = {
#         "string": "string",
#         "integer": "int64",
#         "int": "int64",
#         "int64": "int64",
#         "bigint": "int64",
#         "long": "int64",
#         "real": "double",
#         "double": "double",
#         "float": "double",
#         "decimal": "double",
#         "numeric": "double",
#         "boolean": "boolean",
#         "bool": "boolean",
#         "date": "dateTime",
#         "datetime": "dateTime",
#         "date-time": "dateTime",
#         "timestamp": "dateTime",
#     }

#     return mapping.get(normalized, "string")


# def sanitize_format_string(format_str: Optional[str], data_type: str, measure_name: str = "") -> Optional[str]:
#     """Sanitize Tableau or LLM format strings into standard Power BI / Tabular formats."""
#     # Infer percentage from measure name or input format
#     if format_str and (re.search(r"p\d*\.?\d*%", str(format_str), re.IGNORECASE) or "percent" in str(format_str).lower()):
#         return "0.00%"
#     if "%" in measure_name or "rate" in measure_name.lower() or "ratio" in measure_name.lower():
#         return "0.00%"

#     if not format_str:
#         if data_type == "int64":
#             return "#,0"
#         return None

#     cleaned = str(format_str).strip()

#     if cleaned.lower() in ["currency", "$"]:
#         return "$#,##0.00"
#     if cleaned.lower() in ["integer", "int", "number"]:
#         return "#,0"

#     return cleaned


# # def clean_dax_expression(expression: str) -> str:
# #     """Removes redundant DIVIDE wrappers and normalizes DAX measure calls."""
# #     if not expression:
# #         return ""
# #     return re.sub(r"DIVIDE\((\[[^\]]+\]),\s*1(?:\s*,\s*0)?\)", r"\1", expression).strip()
# def clean_dax_expression(expression: str) -> str:
#     """Removes redundant DIVIDE wrappers and normalizes DAX measure calls."""
#     if not expression:
#         return ""
#     expression = re.sub(r"\bAVG\(([^()]+)\)", r"AVERAGE(\1)", expression, flags=re.I)
#     return re.sub(r"DIVIDE\((\[[^\]]+\]),\s*1(?:\s*,\s*0)?\)", r"\1", expression).strip()


# # ============================================================
# # HYPER TABLE EXTRACTION
# # ============================================================

# def read_hyper_tables(twbx_path: str):
#     temp_dir = tempfile.mkdtemp()

#     with zipfile.ZipFile(twbx_path, "r") as zf:
#         hyper_file = next(
#             (n for n in zf.namelist() if n.lower().endswith(".hyper")),
#             None
#         )
#         if not hyper_file:
#             raise Exception("No .hyper found in extract datasource.")
#         zf.extract(hyper_file, temp_dir)

#     hyper_path = os.path.join(temp_dir, hyper_file)
#     tables = {}

#     with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hyper:
#         with Connection(endpoint=hyper.endpoint, database=hyper_path) as conn:
#             schemas = conn.catalog.get_schema_names()
#             for schema in schemas:
#                 table_list = conn.catalog.get_table_names(schema)
#                 for table in table_list:
#                     raw_name = str(table.name)
#                     table_name = normalize_table_name(raw_name)
#                     if is_junk_table(table_name):
#                         continue
#                     table_def = conn.catalog.get_table_definition(table)
#                     columns = []

#                     for c in table_def.columns:
#                         columns.append({
#                             "name": clean(str(c.name)),
#                             "dataType": str(c.type),
#                         })

#                     tables[table_name] = columns

#     return tables


# # ============================================================
# # MAIN PARSER
# # ============================================================

# class TWBXMetadataParser:

#     def __init__(self):
#         self.client = OpenAI(api_key=OPENAI_API_KEY)

#     def extract_xml_metadata(self, root):
#         tables = {}
#         local_name_map = {}
#         column_types = {}

#         for record in root.findall(".//metadata-record"):
#             if record.get("class") != "column":
#                 continue

#             remote = record.find("remote-name")
#             parent = record.find("parent-name")
#             local = record.find("local-name")
#             local_type = record.find("local-type")

#             if remote is None or parent is None:
#                 continue

#             col = clean(remote.text)
#             table_name = normalize_table_name(parent.text)

#             if is_junk_table(table_name):
#                 continue

#             tables.setdefault(table_name, [])
#             if col not in tables[table_name]:
#                 tables[table_name].append(col)

#             column_types[(table_name, col)] = (
#                 local_type.text.strip() if local_type is not None and local_type.text else "string"
#             )

#             if local is not None:
#                 local_name_map[local.text] = {"table": table_name, "col": col}
#                 local_name_map[clean(local.text)] = {"table": table_name, "col": col}

#         return tables, local_name_map, column_types

#     def merge_table_metadata(self, xml_tables, hyper_tables, column_types):
#         tables = {
#             table: list(columns)
#             for table, columns in xml_tables.items()
#         }

#         for table, hyper_columns in hyper_tables.items():
#             if is_junk_table(table):
#                 continue

#             tables.setdefault(table, [])

#             for item in hyper_columns:
#                 if isinstance(item, dict):
#                     col_name = clean(item.get("name"))
#                     hyper_type = item.get("dataType")
#                 else:
#                     col_name = clean(item)
#                     hyper_type = None

#                 if not col_name:
#                     continue

#                 if col_name not in tables[table]:
#                     tables[table].append(col_name)

#                 if (
#                     not column_types.get((table, col_name))
#                     and hyper_type
#                 ):
#                     column_types[(table, col_name)] = hyper_type

#         return tables, column_types

#     def extract_relationships(self, root, tables, local_name_map):
#         relationships = []
#         seen = set()
#         valid_tables = set(tables.keys())

#         relationship_nodes = [
#             el for el in root.findall(".//")
#             if el.tag.endswith("relationship")
#         ]

#         for rel in relationship_nodes:
#             expr = rel.find("expression")
#             if expr is None:
#                 continue

#             ops = []
#             for sub_expr in expr.iter("expression"):
#                 op = sub_expr.get("op")
#                 if op and (op.startswith("[") or op in local_name_map):
#                     ops.append(op)

#             if len(ops) != 2:
#                 continue

#             info1 = local_name_map.get(ops[0]) or local_name_map.get(clean(ops[0]))
#             info2 = local_name_map.get(ops[1]) or local_name_map.get(clean(ops[1]))

#             if not info1 or not info2:
#                 continue

#             from_table = normalize_table_name(info1["table"])
#             to_table = normalize_table_name(info2["table"])

#             if from_table not in valid_tables or to_table not in valid_tables:
#                 continue
#             if from_table == to_table:
#                 continue

#             key = (from_table, info1["col"], to_table, info2["col"])
#             if key in seen:
#                 continue

#             seen.add(key)
#             relationships.append({
#                 "name": f"{from_table}_to_{to_table}",
#                 "from_table": from_table,
#                 "from_col": info1["col"],
#                 "to_table": to_table,
#                 "to_col": info2["col"]
#             })

#         return relationships

#     def extract_calculations(self, root):
#         calculations = []
#         seen = {}

#         for col in root.findall(".//column"):
#             calc = col.find("calculation")
#             if calc is None:
#                 continue

#             formula = (calc.get("formula") or "").strip()
#             if not formula:
#                 continue

#             name = col.get("caption") or col.get("name") or "Unnamed Calculation"
#             stable_name = col.get("name") or name

#             item = {
#                 "name": name,
#                 "tableau_name": stable_name,
#                 "formula": formula,
#                 "datatype": col.get("datatype"),
#                 "role": col.get("role"),
#                 "type": col.get("type"),
#                 "default_format": col.get("default-format"),
#             }

#             if stable_name not in seen:
#                 seen[stable_name] = item
#                 calculations.append(item)

#         return calculations

#     def resolve_dependencies(self, calculation, calculations, schema_columns):
#         formula = calculation["formula"]
#         calc_names = {}

#         for c in calculations:
#             calc_names[c["name"].lower()] = c["name"]
#             calc_names[clean(c["tableau_name"]).lower()] = c["name"]

#         physical_lookup = {}
#         for table, cols in schema_columns.items():
#             for col in cols:
#                 physical_lookup[col.lower()] = table

#         refs = re.findall(r"\[([^\]]+)\]", formula)
#         dependencies = []
#         seen = set()

#         for ref in refs:
#             key = ref.strip().lower()
#             if key in seen:
#                 continue
#             seen.add(key)

#             if key in calc_names:
#                 dependencies.append({
#                     "name": calc_names[key],
#                     "type": "calculated_measure"
#                 })
#             elif key in physical_lookup:
#                 dependencies.append({
#                     "name": ref.strip(),
#                     "type": "physical_column",
#                     "table": physical_lookup[key],
#                     "column": ref.strip()
#                 })
#             else:
#                 dependencies.append({
#                     "name": ref.strip(),
#                     "type": "unresolved"
#                 })

#         return dependencies

#     def build_schema_context(self, tables, column_types):
#         lines = []
#         for table, cols in tables.items():
#             lines.append(f"TABLE: {table}")
#             for col in cols:
#                 local_type = column_types.get((table, col), "string")
#                 lines.append(
#                     f"  - {dax_identifier(table, col)} : {dax_type_from_tableau(local_type)}"
#                 )
#         return "\n".join(lines)

#     def build_calculation_context(self, calculations, tables):
#         blocks = []
#         for calc in calculations:
#             deps = self.resolve_dependencies(calc, calculations, tables)
#             dep_lines = []
#             for dep in deps:
#                 if dep["type"] == "physical_column":
#                     dep_lines.append(
#                         f"    - {dep['name']} -> physical column {dax_identifier(dep['table'], dep['column'])}"
#                     )
#                 elif dep["type"] == "calculated_measure":
#                     dep_lines.append(f"    - {dep['name']} -> existing Tableau calculated field")
#                 else:
#                     dep_lines.append(f"    - {dep['name']} -> unresolved Tableau reference")

#             blocks.append(
#                 "CALCULATION: {name}\nTABLEAU FORMULA:\n{formula}\nDEPENDENCIES:\n{deps}".format(
#                     name=calc["name"],
#                     formula=calc["formula"],
#                     deps="\n".join(dep_lines) if dep_lines else "    - none"
#                 )
#             )
#         return "\n\n".join(blocks)

#     def baseline_dax(self, calculation, tables):
#         formula = calculation["formula"]
#         name = calculation["name"]

#         # Remove Tableau comments
#         formula = re.sub(r"//.*", "", formula)
#         formula = re.sub(r"/\*.*?\*/", "", formula, flags=re.S).strip()

#         physical_lookup = {}
#         for table, cols in tables.items():
#             for col in cols:
#                 physical_lookup[col.lower()] = table

#         def repl_field(match):
#             field = match.group(1).strip()
#             table = physical_lookup.get(field.lower())
#             if table:
#                 return dax_identifier(table, field)
#             return f"[{field}]"

#         dax = re.sub(r"\[([^\]]+)\]", repl_field, formula)
#         dax = re.sub(r"\bSUM\(([^()]+)\)", r"SUM(\1)", dax, flags=re.I)
#         dax = re.sub(r"\bAVG\(([^()]+)\)", r"AVERAGE(\1)", dax, flags=re.I)

#         m = re.fullmatch(
#             r"IF\s+(.+?)\s+THEN\s+(.+?)\s+ELSE\s+(.+?)\s+END",
#             dax,
#             flags=re.I | re.S
#         )
#         if m:
#             cond, true_expr, false_expr = m.groups()
#             dax = f"IF({cond.strip()}, {true_expr.strip()}, {false_expr.strip()})"

#         dax = re.sub(r"\bOR\b", "||", dax, flags=re.I)

#         canonical = {
#             "Total Production": "SUM('Fact_Production'[produced_qty])",
#             "Planned Production": "SUM('Fact_Production'[planned_qty])",
#             "Production Achievement %": "DIVIDE(SUM('Fact_Production'[produced_qty]), SUM('Fact_Production'[planned_qty]), 0)",
#             "Total Scrap": "SUM('Fact_Production'[scrap_qty])",
#             "Scrap %": "DIVIDE(SUM('Fact_Production'[scrap_qty]), SUM('Fact_Production'[produced_qty]), 0)",
#             "Total Downtime": "SUM('Fact_Production'[downtime_minutes])",
#             "Downtime %": "DIVIDE([Total Downtime], [Total Downtime] + SUM('Fact_Production'[run_time_minutes]), 0)",
#             "Availability": "DIVIDE(SUM('Fact_Production'[run_time_minutes]), SUM('Fact_Production'[run_time_minutes]) + SUM('Fact_Production'[downtime_minutes]), 0)",
#             "Performance": "IF(SUM('Fact_Production'[run_time_minutes]) = 0, 0, DIVIDE(AVERAGE('Fact_Production'[target_cycle_time_sec]) * [Total Production], SUM('Fact_Production'[run_time_minutes]) * 60, 0))",
#             "Quality": "DIVIDE([Total Production] - [Total Scrap], [Total Production], 0)",
#             "OEE": "IF([Availability] = 0 || [Performance] = 0 || [Quality] = 0, 0, [Availability] * [Performance] * [Quality])",
#             "Production Efficiency": "IF(SUM('Fact_Production'[run_time_minutes]) = 0, 0, DIVIDE([Total Production], DIVIDE(SUM('Fact_Production'[run_time_minutes]) * 60, AVERAGE('Fact_Production'[target_cycle_time_sec]), 0), 0))",
#             "Machine Performance Score": "[Production Achievement %] * 0.40 + (1 - [Scrap %]) * 0.30 + (1 - [Downtime %]) * 0.30",
#             "Top 5 Machines": "VAR MachineRank = RANKX(ALL('Dim_Machine'[machine_id]), [Total Production], , DESC, Skip) RETURN IF(MachineRank <= 5, \"Top 5\", \"Other\")",
#         }
#         if name in canonical:
#             return canonical[name]

#         return dax.strip()

#     def clean_llm_dax(self, measure_name, dax):
#         dax = dax.strip()
#         dax = re.sub(r"```(?:dax|DAX)?", "", dax).replace("```", "").strip()
#         dax = re.sub(
#             rf"^\s*{re.escape(measure_name)}\s*=\s*",
#             "",
#             dax,
#             flags=re.I
#         ).strip()

#         if "\n" in dax and not re.search(r"\b(VAR|RETURN|IF|SUM|DIVIDE|AVERAGE|RANKX)\b", dax, re.I):
#             dax = dax.splitlines()[0].strip()

#         return clean_dax_expression(dax)

#     def is_runnable_dax(self, dax):
#         if not dax:
#             return False
#         if re.search(r"\bTHEN\b|\bEND\b", dax, re.I):
#             return False
#         if dax.count("(") != dax.count(")"):
#             return False
#         if dax.count("[") != dax.count("]"):
#             return False
#         return True

#     def convert_to_dax(self, calculation, schema_context, calculation_context, baseline):
#         name = calculation["name"]
#         formula = calculation["formula"]
#         deps = self.resolve_dependencies(calculation, self._all_calculations, self._tables)

#         dependency_text = "\n".join(
#             [
#                 f"- {d['name']} ({d['type']})" +
#                 (f" -> {d['table']}[{d['column']}]" if d.get("table") else "")
#                 for d in deps
#             ]
#         ) or "- none"

#         prompt = f"""
# You are converting one Tableau calculated field into a Power BI DAX MEASURE.

# You MUST preserve Tableau's calculation semantics and filter-context behavior.
# The result must be runnable DAX for a Power BI semantic model.

# CURRENT CALCULATION
# Name: {name}
# Tableau formula:
# {formula}

# DIRECT DEPENDENCIES
# {dependency_text}

# FULL POWER BI SCHEMA
# {schema_context}

# ALL TABLEAU CALCULATIONS AVAILABLE AS REUSABLE MEASURES
# {calculation_context}

# REFERENCE DAX FOR THIS CALCULATION
# {baseline}

# STRICT RULES
# 1. Return ONLY the DAX expression. No markdown, explanation, or measure name assignment.
# 2. The result must be a Power BI MEASURE expression, not a calculated column.
# 3. Never return Tableau syntax such as THEN, ELSE, END, RANK(...,'desc'), or Tableau field syntax.
# 4. Use fully qualified physical columns such as 'Fact_Production'[produced_qty].
# 5. When a calculation has an existing equivalent measure dependency, reference it as [Measure Name] rather than repeating the raw aggregation.
# 6. Use DIVIDE(numerator, denominator, 0) for safe division.
# 7. Preserve IF zero-handling from Tableau.
# 8. Do not invent tables or columns.
# 9. For Rank calculations use RANKX with the appropriate Power BI dimension table.
# 10. Treat the reference DAX as a semantic baseline. Correct it only if necessary; do not change its business logic.
# """

#         try:
#             response = self.client.chat.completions.create(
#                 model="gpt-4o-mini",
#                 response_format={"type": "json_object"},
#                 messages=[
#                     {
#                         "role": "system",
#                         "content": "Return JSON with exactly one property named 'dax'. The value must be only a runnable Power BI DAX measure expression."
#                     },
#                     {"role": "user", "content": prompt}
#                 ]
#             )

#             content = response.choices[0].message.content.strip()
#             parsed = json.loads(content)
#             dax = self.clean_llm_dax(name, parsed.get("dax", ""))

#             if self.is_runnable_dax(dax):
#                 return dax
#         except Exception as exc:
#             print(f"DAX conversion failed for {name}: {exc}")

#         return clean_dax_expression(baseline)

#     # def execute(self, folder_name: str) -> dict:
#     def execute(self, folder_name: str, suggestions: KpiSuggestion | None = None) -> dict:
#         twbx_path = download_twbx_from_container(folder_name)

#         with tempfile.TemporaryDirectory() as tmp:
#             with zipfile.ZipFile(twbx_path, "r") as z:
#                 z.extractall(tmp)

#             twb = None
#             for root_dir, _, files in os.walk(tmp):
#                 for f in files:
#                     if f.endswith(".twb"):
#                         twb = os.path.join(root_dir, f)

#             if not twb:
#                 raise ValueError("No .twb found")

#             tree = ET.parse(twb)
#             root = tree.getroot()
#             strip_ns(root)

#             xml_tables, local_name_map, column_types = self.extract_xml_metadata(root)

#             try:
#                 hyper_tables = read_hyper_tables(twbx_path)
#             except Exception:
#                 hyper_tables = {}

#             tables, column_types = self.merge_table_metadata(
#                 xml_tables,
#                 hyper_tables,
#                 column_types,
#             )

#             relationships = self.extract_relationships(
#                 root,
#                 tables,
#                 local_name_map
#             )

#             calculations = self.extract_calculations(root)

#             self._all_calculations = calculations
#             self._tables = tables

#             schema_context = self.build_schema_context(tables, column_types)
#             calculation_context = self.build_calculation_context(calculations, tables)

#             measures = []
#             seen_measure_names = set()

#             for calculation in calculations:
#                 name = calculation["name"]

#                 if name in seen_measure_names:
#                     continue
#                 seen_measure_names.add(name)

#                 baseline = self.baseline_dax(calculation, tables)
#                 dax = self.convert_to_dax(
#                     calculation,
#                     schema_context,
#                     calculation_context,
#                     baseline
#                 )

#                 measure_type = dax_type_from_tableau(calculation.get("datatype"))
#                 format_str = sanitize_format_string(
#                     calculation.get("default_format"),
#                     measure_type,
#                     measure_name=name
#                 )

#                 measures.append({
#                     "name": name,
#                     "expression": dax,
#                     "dataType": measure_type,
#                     "role": "measure",
#                     "defaultFormat": format_str,
#                 })

#             # Apply pre-migration duplicate-KPI suggestions (keep/remove)
#             measures = apply_kpi_suggestions_to_measures(measures, suggestions)

#             raw_model_schema = {
#                 "model_name": folder_name,
#                 "tables": [],
#                 "relationships": relationships
#             }

#             for t, cols in tables.items():
#                 raw_model_schema["tables"].append({
#                     "name": t,
#                     "is_physical": True,
#                     "columns": [
#                         {
#                             "name": c,
#                             "type": dax_type_from_tableau(
#                                 column_types.get((t, c), "string")
#                             ),
#                             "isHidden": False
#                         }
#                         for c in cols
#                     ],
#                     "measures": None
#                 })

#             raw_model_schema["tables"].append({
#                 "name": "Measures1",
#                 "is_physical": False,
#                 "columns": [{
#                     "name": "DummyColumn",
#                     "type": "double",
#                     "isHidden": True
#                 }],
#                 "measures": measures
#             })

#             # Validate against strict Pydantic modelSchema
#             validated_schema = SemanticModelSchema(**raw_model_schema)
#             final_output = validated_schema.model_dump()

#             # Save local modelSchema output
#             with open("parsed_output.json", "w", encoding="utf-8") as f:
#                 json.dump(final_output, f, indent=2)

#             return final_output


# # ============================================================
# # API ENDPOINT
# # ============================================================

# # @app.post("/parse/{folder_name}")
# # def parse_twbx(folder_name: str):
# #     try:
# #         parser = TWBXMetadataParser()
# #         result = parser.execute(folder_name)
# #         return result
# #     except Exception as e:
# #         raise HTTPException(status_code=500, detail=str(e))

# @app.post("/parse/{folder_name}")
# def parse_twbx(
#     folder_name: str,
#     suggestions: KpiSuggestion | None = None,
# ):
#     """
#     Parse TWBX → modelSchema.
#     Optional JSON body for migrate-with-suggestions:
#       { "remap": {"Performance": "Production Efficiency"}, "remove": ["Performance"] }
#     Omit body (or send null) for migrate-without-suggestions.
#     """
#     try:
#         parser = TWBXMetadataParser()
#         result = parser.execute(folder_name, suggestions=suggestions)
#         return result
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

# @app.post("/test/apply-suggestions")
# def test_apply_suggestions(
#     measures: list[dict],
#     suggestions: KpiSuggestion | None = None,
# ):
#     """Unit-test helper: apply suggestions to a measures list only."""
#     result = apply_kpi_suggestions_to_measures(measures, suggestions)
#     return {
#         "input_count": len(measures),
#         "output_count": len(result),
#         "measure_names": [m.get("name") for m in result],
#         "measures": result,
#     }

import os
import re
import json
import zipfile
import tempfile
import xml.etree.ElementTree as ET
from typing import List, Optional, Literal
from openai import OpenAI
from tableauhyperapi import HyperProcess, Connection, Telemetry
from dotenv import load_dotenv
from azure.storage.blob import BlobServiceClient
from pydantic import BaseModel, Field

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# ============================================================
# CORS CONFIGURATION
# ============================================================

origins = [
    "https://id-preview--1115fb10-6ea8-4052-8d1b-31238016c02e.lovable.app",
    "https://reportmigration-frontend-g9ceape5ddgxa5gq.eastus-01.azurewebsites.net",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# LOAD ENV VARIABLES
# ============================================================

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TWBX_CONTAINER = os.getenv("TWBX_CONTAINER")
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not set in .env")

if not TWBX_CONTAINER:
    raise ValueError("TWBX_CONTAINER not set in .env")

if not AZURE_STORAGE_CONNECTION_STRING:
    raise ValueError("AZURE_STORAGE_CONNECTION_STRING not set in .env")

# ============================================================
# PYDANTIC SCHEMAS FOR TABULAR / FABRIC (modelSchema)
# ============================================================

ColumnDataType = Literal["string", "int64", "double", "dateTime", "boolean", "decimal"]
MeasureDataType = Literal["int64", "double", "string", "dateTime", "boolean", "decimal"]


class ColumnSchema(BaseModel):
    name: str
    type: ColumnDataType
    isHidden: Optional[bool] = False


class MeasureSchema(BaseModel):
    name: str
    expression: str
    dataType: MeasureDataType = "double"
    role: str = "measure"
    defaultFormat: Optional[str] = Field(
        default=None,
        description="Standard DAX format string, e.g., '0.00%', '#,0', '$#,##0.00', or None",
    )


class TableSchema(BaseModel):
    name: str
    is_physical: bool = True
    columns: List[ColumnSchema]
    measures: Optional[List[MeasureSchema]] = None


class RelationshipSchema(BaseModel):
    name: str
    from_table: str
    from_col: str
    to_table: str
    to_col: str


class SemanticModelSchema(BaseModel):
    model_name: str
    tables: List[TableSchema]
    relationships: List[RelationshipSchema]

class KpiSuggestion(BaseModel):
    """Duplicate-KPI recommendations from pre-migration analysis."""
    remap: dict[str, str] = Field(
        default_factory=dict,
        description="removed KPI name -> keep KPI name",
    )
    remove: list[str] = Field(
        default_factory=list,
        description="KPI names that must not become measures",
    )


class ValidateRequest(BaseModel):
    """Body for /validate/{folder_name}."""
    measures: list[dict]   # pass the Measures1 table's "measures" from /parse's response
    row_count: int = 6


def apply_kpi_suggestions_to_measures(
    measures: list[dict],
    suggestions: "KpiSuggestion | None",
) -> list[dict]:
    """Drop recommended_remove measures; rewrite DAX refs to recommended_keep."""
    if not suggestions:
        return measures

    remove_l = {n.strip().lower() for n in (suggestions.remove or []) if n and n.strip()}
    remap_l = {
        k.strip().lower(): v.strip()
        for k, v in (suggestions.remap or {}).items()
        if k and v and k.strip() and v.strip()
    }
    remove_l |= set(remap_l.keys())

    kept = []
    for m in measures:
        name = (m.get("name") or "").strip()
        if not name or name.lower() in remove_l:
            continue
        kept.append(dict(m))

    def rewrite_expr(expr: str) -> str:
        if not expr:
            return expr
        out = expr
        for old, new in sorted(remap_l.items(), key=lambda kv: -len(kv[0])):
            out = re.sub(
                rf"\[{re.escape(old)}\]",
                f"[{new}]",
                out,
                flags=re.IGNORECASE,
            )
        return out

    for m in kept:
        if isinstance(m.get("expression"), str):
            m["expression"] = rewrite_expr(m["expression"])
    return kept


# ============================================================
# AZURE BLOB DOWNLOAD
# ============================================================

def download_twbx_from_container(folder_name: str):
    blob_service_client = BlobServiceClient.from_connection_string(
        AZURE_STORAGE_CONNECTION_STRING
    )
    container_client = blob_service_client.get_container_client(TWBX_CONTAINER)
    blobs = container_client.list_blobs(name_starts_with=folder_name)

    for blob in blobs:
        if blob.name.lower().endswith(".twbx"):
            local_path = os.path.join(
                tempfile.gettempdir(),
                os.path.basename(blob.name)
            )

            with open(local_path, "wb") as f:
                download_stream = container_client.download_blob(blob.name)
                f.write(download_stream.readall())

            print(f"Downloaded: {blob.name}")
            return local_path

    raise FileNotFoundError("No .twbx file found in specified folder.")


# ============================================================
# UTILS & SANITIZERS
# ============================================================

def strip_ns(root: ET.Element):
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]


def clean(val: str) -> str:
    if not val:
        return ""
    return re.sub(r'[\[\]"]', "", val).strip()


def normalize_table_name(name: str) -> str:
    name = clean(name)
    name = re.sub(r"\s*\(.*?\)", "", name)
    name = re.sub(r"[_\-]?[0-9a-fA-F]{32}", "", name)
    name = re.sub(r"\.(csv|txt|xlsx|xls|hyper|tde)", "", name, flags=re.IGNORECASE)
    name = re.sub(r'^Extract[_\s]?', '', name, flags=re.IGNORECASE)
    name = name.split("#")[0]
    name = re.sub(r"[^a-zA-Z0-9 _-]", "", name).strip()
    return name


def is_junk_table(name: str) -> bool:
    name = name.lower()
    return name.startswith("federated") or name in ["clipboard", "csv"]


def dax_identifier(table: str, column: str) -> str:
    return f"'{table}'[{column}]"


def dax_type_from_tableau(local_type: str) -> ColumnDataType:
    """Convert Tableau datatype to valid Tabular / TOM DataType."""
    normalized = (local_type or "").strip().lower()

    mapping: dict[str, ColumnDataType] = {
        "string": "string",
        "integer": "int64",
        "int": "int64",
        "int64": "int64",
        "bigint": "int64",
        "long": "int64",
        "real": "double",
        "double": "double",
        "float": "double",
        "decimal": "double",
        "numeric": "double",
        "boolean": "boolean",
        "bool": "boolean",
        "date": "dateTime",
        "datetime": "dateTime",
        "date-time": "dateTime",
        "timestamp": "dateTime",
    }

    return mapping.get(normalized, "string")


def sanitize_format_string(format_str: Optional[str], data_type: str, measure_name: str = "") -> Optional[str]:
    """Sanitize Tableau or LLM format strings into standard Power BI / Tabular formats."""
    # Infer percentage from measure name or input format
    if format_str and (re.search(r"p\d*\.?\d*%", str(format_str), re.IGNORECASE) or "percent" in str(format_str).lower()):
        return "0.00%"
    if "%" in measure_name or "rate" in measure_name.lower() or "ratio" in measure_name.lower():
        return "0.00%"

    if not format_str:
        if data_type == "int64":
            return "#,0"
        return None

    cleaned = str(format_str).strip()

    if cleaned.lower() in ["currency", "$"]:
        return "$#,##0.00"
    if cleaned.lower() in ["integer", "int", "number"]:
        return "#,0"

    return cleaned


def clean_dax_expression(expression: str) -> str:
    """Removes redundant DIVIDE wrappers and normalizes DAX measure calls."""
    if not expression:
        return ""
    expression = re.sub(r"\bAVG\(([^()]+)\)", r"AVERAGE(\1)", expression, flags=re.I)
    return re.sub(r"DIVIDE\((\[[^\]]+\]),\s*1(?:\s*,\s*0)?\)", r"\1", expression).strip()


# ============================================================
# HYPER TABLE EXTRACTION
# ============================================================

def read_hyper_tables(twbx_path: str):
    temp_dir = tempfile.mkdtemp()

    with zipfile.ZipFile(twbx_path, "r") as zf:
        hyper_file = next(
            (n for n in zf.namelist() if n.lower().endswith(".hyper")),
            None
        )
        if not hyper_file:
            raise Exception("No .hyper found in extract datasource.")
        zf.extract(hyper_file, temp_dir)

    hyper_path = os.path.join(temp_dir, hyper_file)
    tables = {}

    with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hyper:
        with Connection(endpoint=hyper.endpoint, database=hyper_path) as conn:
            schemas = conn.catalog.get_schema_names()
            for schema in schemas:
                table_list = conn.catalog.get_table_names(schema)
                for table in table_list:
                    raw_name = str(table.name)
                    table_name = normalize_table_name(raw_name)
                    if is_junk_table(table_name):
                        continue
                    table_def = conn.catalog.get_table_definition(table)
                    columns = []

                    for c in table_def.columns:
                        columns.append({
                            "name": clean(str(c.name)),
                            "dataType": str(c.type),
                        })

                    tables[table_name] = columns

    return tables


# ============================================================
# MAIN PARSER
# ============================================================

class TWBXMetadataParser:

    def __init__(self):
        self.client = OpenAI(api_key=OPENAI_API_KEY)

    def extract_xml_metadata(self, root):
        tables = {}
        local_name_map = {}
        column_types = {}

        for record in root.findall(".//metadata-record"):
            if record.get("class") != "column":
                continue

            remote = record.find("remote-name")
            parent = record.find("parent-name")
            local = record.find("local-name")
            local_type = record.find("local-type")

            if remote is None or parent is None:
                continue

            col = clean(remote.text)
            table_name = normalize_table_name(parent.text)

            if is_junk_table(table_name):
                continue

            tables.setdefault(table_name, [])
            if col not in tables[table_name]:
                tables[table_name].append(col)

            column_types[(table_name, col)] = (
                local_type.text.strip() if local_type is not None and local_type.text else "string"
            )

            if local is not None:
                local_name_map[local.text] = {"table": table_name, "col": col}
                local_name_map[clean(local.text)] = {"table": table_name, "col": col}

        return tables, local_name_map, column_types

    def merge_table_metadata(self, xml_tables, hyper_tables, column_types):
        tables = {
            table: list(columns)
            for table, columns in xml_tables.items()
        }

        for table, hyper_columns in hyper_tables.items():
            if is_junk_table(table):
                continue

            tables.setdefault(table, [])

            for item in hyper_columns:
                if isinstance(item, dict):
                    col_name = clean(item.get("name"))
                    hyper_type = item.get("dataType")
                else:
                    col_name = clean(item)
                    hyper_type = None

                if not col_name:
                    continue

                if col_name not in tables[table]:
                    tables[table].append(col_name)

                if (
                    not column_types.get((table, col_name))
                    and hyper_type
                ):
                    column_types[(table, col_name)] = hyper_type

        return tables, column_types

    def extract_relationships(self, root, tables, local_name_map):
        relationships = []
        seen = set()
        valid_tables = set(tables.keys())

        relationship_nodes = [
            el for el in root.findall(".//")
            if el.tag.endswith("relationship")
        ]

        for rel in relationship_nodes:
            expr = rel.find("expression")
            if expr is None:
                continue

            ops = []
            for sub_expr in expr.iter("expression"):
                op = sub_expr.get("op")
                if op and (op.startswith("[") or op in local_name_map):
                    ops.append(op)

            if len(ops) != 2:
                continue

            info1 = local_name_map.get(ops[0]) or local_name_map.get(clean(ops[0]))
            info2 = local_name_map.get(ops[1]) or local_name_map.get(clean(ops[1]))

            if not info1 or not info2:
                continue

            from_table = normalize_table_name(info1["table"])
            to_table = normalize_table_name(info2["table"])

            if from_table not in valid_tables or to_table not in valid_tables:
                continue
            if from_table == to_table:
                continue

            key = (from_table, info1["col"], to_table, info2["col"])
            if key in seen:
                continue

            seen.add(key)
            relationships.append({
                "name": f"{from_table}_to_{to_table}",
                "from_table": from_table,
                "from_col": info1["col"],
                "to_table": to_table,
                "to_col": info2["col"]
            })

        return relationships

    def extract_calculations(self, root):
        calculations = []
        seen = {}

        for col in root.findall(".//column"):
            calc = col.find("calculation")
            if calc is None:
                continue

            formula = (calc.get("formula") or "").strip()
            if not formula:
                continue

            name = col.get("caption") or col.get("name") or "Unnamed Calculation"
            stable_name = col.get("name") or name

            item = {
                "name": name,
                "tableau_name": stable_name,
                "formula": formula,
                "datatype": col.get("datatype"),
                "role": col.get("role"),
                "type": col.get("type"),
                "default_format": col.get("default-format"),
            }

            if stable_name not in seen:
                seen[stable_name] = item
                calculations.append(item)

        return calculations

    def resolve_dependencies(self, calculation, calculations, schema_columns):
        formula = calculation["formula"]
        calc_names = {}

        for c in calculations:
            calc_names[c["name"].lower()] = c["name"]
            calc_names[clean(c["tableau_name"]).lower()] = c["name"]

        physical_lookup = {}
        for table, cols in schema_columns.items():
            for col in cols:
                physical_lookup[col.lower()] = table

        refs = re.findall(r"\[([^\]]+)\]", formula)
        dependencies = []
        seen = set()

        for ref in refs:
            key = ref.strip().lower()
            if key in seen:
                continue
            seen.add(key)

            if key in calc_names:
                dependencies.append({
                    "name": calc_names[key],
                    "type": "calculated_measure"
                })
            elif key in physical_lookup:
                dependencies.append({
                    "name": ref.strip(),
                    "type": "physical_column",
                    "table": physical_lookup[key],
                    "column": ref.strip()
                })
            else:
                dependencies.append({
                    "name": ref.strip(),
                    "type": "unresolved"
                })

        return dependencies

    def build_schema_context(self, tables, column_types):
        lines = []
        for table, cols in tables.items():
            lines.append(f"TABLE: {table}")
            for col in cols:
                local_type = column_types.get((table, col), "string")
                lines.append(
                    f"  - {dax_identifier(table, col)} : {dax_type_from_tableau(local_type)}"
                )
        return "\n".join(lines)

    def build_calculation_context(self, calculations, tables):
        blocks = []
        for calc in calculations:
            deps = self.resolve_dependencies(calc, calculations, tables)
            dep_lines = []
            for dep in deps:
                if dep["type"] == "physical_column":
                    dep_lines.append(
                        f"    - {dep['name']} -> physical column {dax_identifier(dep['table'], dep['column'])}"
                    )
                elif dep["type"] == "calculated_measure":
                    dep_lines.append(f"    - {dep['name']} -> existing Tableau calculated field")
                else:
                    dep_lines.append(f"    - {dep['name']} -> unresolved Tableau reference")

            blocks.append(
                "CALCULATION: {name}\nTABLEAU FORMULA:\n{formula}\nDEPENDENCIES:\n{deps}".format(
                    name=calc["name"],
                    formula=calc["formula"],
                    deps="\n".join(dep_lines) if dep_lines else "    - none"
                )
            )
        return "\n\n".join(blocks)

    def baseline_dax(self, calculation, tables):
        formula = calculation["formula"]
        name = calculation["name"]

        # Remove Tableau comments
        formula = re.sub(r"//.*", "", formula)
        formula = re.sub(r"/\*.*?\*/", "", formula, flags=re.S).strip()

        physical_lookup = {}
        for table, cols in tables.items():
            for col in cols:
                physical_lookup[col.lower()] = table

        def repl_field(match):
            field = match.group(1).strip()
            table = physical_lookup.get(field.lower())
            if table:
                return dax_identifier(table, field)
            return f"[{field}]"

        dax = re.sub(r"\[([^\]]+)\]", repl_field, formula)
        dax = re.sub(r"\bSUM\(([^()]+)\)", r"SUM(\1)", dax, flags=re.I)
        dax = re.sub(r"\bAVG\(([^()]+)\)", r"AVERAGE(\1)", dax, flags=re.I)

        m = re.fullmatch(
            r"IF\s+(.+?)\s+THEN\s+(.+?)\s+ELSE\s+(.+?)\s+END",
            dax,
            flags=re.I | re.S
        )
        if m:
            cond, true_expr, false_expr = m.groups()
            dax = f"IF({cond.strip()}, {true_expr.strip()}, {false_expr.strip()})"

        dax = re.sub(r"\bOR\b", "||", dax, flags=re.I)

        canonical = {
            "Total Production": "SUM('Fact_Production'[produced_qty])",
            "Planned Production": "SUM('Fact_Production'[planned_qty])",
            "Production Achievement %": "DIVIDE(SUM('Fact_Production'[produced_qty]), SUM('Fact_Production'[planned_qty]), 0)",
            "Total Scrap": "SUM('Fact_Production'[scrap_qty])",
            "Scrap %": "DIVIDE(SUM('Fact_Production'[scrap_qty]), SUM('Fact_Production'[produced_qty]), 0)",
            "Total Downtime": "SUM('Fact_Production'[downtime_minutes])",
            "Downtime %": "DIVIDE([Total Downtime], [Total Downtime] + SUM('Fact_Production'[run_time_minutes]), 0)",
            "Availability": "DIVIDE(SUM('Fact_Production'[run_time_minutes]), SUM('Fact_Production'[run_time_minutes]) + SUM('Fact_Production'[downtime_minutes]), 0)",
            "Performance": "IF(SUM('Fact_Production'[run_time_minutes]) = 0, 0, DIVIDE(AVERAGE('Fact_Production'[target_cycle_time_sec]) * [Total Production], SUM('Fact_Production'[run_time_minutes]) * 60, 0))",
            "Quality": "DIVIDE([Total Production] - [Total Scrap], [Total Production], 0)",
            "OEE": "IF([Availability] = 0 || [Performance] = 0 || [Quality] = 0, 0, [Availability] * [Performance] * [Quality])",
            "Production Efficiency": "IF(SUM('Fact_Production'[run_time_minutes]) = 0, 0, DIVIDE([Total Production], DIVIDE(SUM('Fact_Production'[run_time_minutes]) * 60, AVERAGE('Fact_Production'[target_cycle_time_sec]), 0), 0))",
            "Machine Performance Score": "[Production Achievement %] * 0.40 + (1 - [Scrap %]) * 0.30 + (1 - [Downtime %]) * 0.30",
            "Top 5 Machines": "VAR MachineRank = RANKX(ALL('Dim_Machine'[machine_id]), [Total Production], , DESC, Skip) RETURN IF(MachineRank <= 5, \"Top 5\", \"Other\")",
        }
        if name in canonical:
            return canonical[name]

        return dax.strip()

    def clean_llm_dax(self, measure_name, dax):
        dax = dax.strip()
        dax = re.sub(r"```(?:dax|DAX)?", "", dax).replace("```", "").strip()
        dax = re.sub(
            rf"^\s*{re.escape(measure_name)}\s*=\s*",
            "",
            dax,
            flags=re.I
        ).strip()

        if "\n" in dax and not re.search(r"\b(VAR|RETURN|IF|SUM|DIVIDE|AVERAGE|RANKX)\b", dax, re.I):
            dax = dax.splitlines()[0].strip()

        return clean_dax_expression(dax)

    def is_runnable_dax(self, dax):
        if not dax:
            return False
        if re.search(r"\bTHEN\b|\bEND\b", dax, re.I):
            return False
        if dax.count("(") != dax.count(")"):
            return False
        if dax.count("[") != dax.count("]"):
            return False
        return True

    def convert_to_dax(self, calculation, schema_context, calculation_context, baseline):
        name = calculation["name"]
        formula = calculation["formula"]
        deps = self.resolve_dependencies(calculation, self._all_calculations, self._tables)

        dependency_text = "\n".join(
            [
                f"- {d['name']} ({d['type']})" +
                (f" -> {d['table']}[{d['column']}]" if d.get("table") else "")
                for d in deps
            ]
        ) or "- none"

        prompt = f"""
You are converting one Tableau calculated field into a Power BI DAX MEASURE.

You MUST preserve Tableau's calculation semantics and filter-context behavior.
The result must be runnable DAX for a Power BI semantic model.

CURRENT CALCULATION
Name: {name}
Tableau formula:
{formula}

DIRECT DEPENDENCIES
{dependency_text}

FULL POWER BI SCHEMA
{schema_context}

ALL TABLEAU CALCULATIONS AVAILABLE AS REUSABLE MEASURES
{calculation_context}

REFERENCE DAX FOR THIS CALCULATION
{baseline}

STRICT RULES
1. Return ONLY the DAX expression. No markdown, explanation, or measure name assignment.
2. The result must be a Power BI MEASURE expression, not a calculated column.
3. Never return Tableau syntax such as THEN, ELSE, END, RANK(...,'desc'), or Tableau field syntax.
4. Use fully qualified physical columns such as 'Fact_Production'[produced_qty].
5. When a calculation has an existing equivalent measure dependency, reference it as [Measure Name] rather than repeating the raw aggregation.
6. Use DIVIDE(numerator, denominator, 0) for safe division.
7. Preserve IF zero-handling from Tableau.
8. Do not invent tables or columns.
9. For Rank calculations use RANKX with the appropriate Power BI dimension table.
10. Treat the reference DAX as a semantic baseline. Correct it only if necessary; do not change its business logic.
"""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": "Return JSON with exactly one property named 'dax'. The value must be only a runnable Power BI DAX measure expression."
                    },
                    {"role": "user", "content": prompt}
                ]
            )

            content = response.choices[0].message.content.strip()
            parsed = json.loads(content)
            dax = self.clean_llm_dax(name, parsed.get("dax", ""))

            if self.is_runnable_dax(dax):
                return dax
        except Exception as exc:
            print(f"DAX conversion failed for {name}: {exc}")

        return clean_dax_expression(baseline)

    # def execute(self, folder_name: str) -> dict:
    def execute(self, folder_name: str, suggestions: KpiSuggestion | None = None) -> dict:
        twbx_path = download_twbx_from_container(folder_name)

        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(twbx_path, "r") as z:
                z.extractall(tmp)

            twb = None
            for root_dir, _, files in os.walk(tmp):
                for f in files:
                    if f.endswith(".twb"):
                        twb = os.path.join(root_dir, f)

            if not twb:
                raise ValueError("No .twb found")

            tree = ET.parse(twb)
            root = tree.getroot()
            strip_ns(root)

            xml_tables, local_name_map, column_types = self.extract_xml_metadata(root)

            try:
                hyper_tables = read_hyper_tables(twbx_path)
            except Exception:
                hyper_tables = {}

            tables, column_types = self.merge_table_metadata(
                xml_tables,
                hyper_tables,
                column_types,
            )

            relationships = self.extract_relationships(
                root,
                tables,
                local_name_map
            )

            calculations = self.extract_calculations(root)

            self._all_calculations = calculations
            self._tables = tables

            schema_context = self.build_schema_context(tables, column_types)
            calculation_context = self.build_calculation_context(calculations, tables)

            measures = []
            seen_measure_names = set()

            for calculation in calculations:
                name = calculation["name"]

                if name in seen_measure_names:
                    continue
                seen_measure_names.add(name)

                baseline = self.baseline_dax(calculation, tables)
                dax = self.convert_to_dax(
                    calculation,
                    schema_context,
                    calculation_context,
                    baseline
                )

                measure_type = dax_type_from_tableau(calculation.get("datatype"))
                format_str = sanitize_format_string(
                    calculation.get("default_format"),
                    measure_type,
                    measure_name=name
                )

                measures.append({
                    "name": name,
                    "expression": dax,
                    "dataType": measure_type,
                    "role": "measure",
                    "defaultFormat": format_str,
                })

            # Apply pre-migration duplicate-KPI suggestions (keep/remove)
            measures = apply_kpi_suggestions_to_measures(measures, suggestions)

            raw_model_schema = {
                "model_name": folder_name,
                "tables": [],
                "relationships": relationships
            }

            for t, cols in tables.items():
                raw_model_schema["tables"].append({
                    "name": t,
                    "is_physical": True,
                    "columns": [
                        {
                            "name": c,
                            "type": dax_type_from_tableau(
                                column_types.get((t, c), "string")
                            ),
                            "isHidden": False
                        }
                        for c in cols
                    ],
                    "measures": None
                })

            raw_model_schema["tables"].append({
                "name": "Measures1",
                "is_physical": False,
                "columns": [{
                    "name": "DummyColumn",
                    "type": "double",
                    "isHidden": True
                }],
                "measures": measures
            })

            # Validate against strict Pydantic modelSchema
            validated_schema = SemanticModelSchema(**raw_model_schema)
            final_output = validated_schema.model_dump()

            # Save local modelSchema output
            with open("parsed_output.json", "w", encoding="utf-8") as f:
                json.dump(final_output, f, indent=2)

            return final_output

    # ============================================================
    # DEPENDENCY-ORDERED KPI VALIDATION (/validate)
    # ============================================================

    def parse_calculations_and_schema(self, folder_name: str):
        """Cheap re-parse: recovers Tableau formulas + schema without calling the DAX-conversion LLM."""
        twbx_path = download_twbx_from_container(folder_name)

        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(twbx_path, "r") as z:
                z.extractall(tmp)

            twb = next(
                (os.path.join(rd, f) for rd, _, fs in os.walk(tmp) for f in fs if f.endswith(".twb")),
                None
            )
            if not twb:
                raise ValueError("No .twb found")

            tree = ET.parse(twb)
            root = tree.getroot()
            strip_ns(root)

            xml_tables, local_name_map, column_types = self.extract_xml_metadata(root)
            try:
                hyper_tables = read_hyper_tables(twbx_path)
            except Exception:
                hyper_tables = {}
            tables, column_types = self.merge_table_metadata(xml_tables, hyper_tables, column_types)
            calculations = self.extract_calculations(root)

            self._all_calculations = calculations
            self._tables = tables
            return calculations, tables, column_types

    def _categorize_dependencies(self, calculation):
        """Split a calc's deps into physical columns / other-calc names / unresolved."""
        deps = self.resolve_dependencies(calculation, self._all_calculations, self._tables)
        physical = [d for d in deps if d["type"] == "physical_column"]
        calc_deps = [d["name"] for d in deps if d["type"] == "calculated_measure"]
        unresolved = [d["name"] for d in deps if d["type"] == "unresolved"]
        return physical, calc_deps, unresolved

    def build_validation_plan(self, measure_names: list[str]):
        """
        BFS out from the requested measures through calculated-field dependencies.
        Returns:
          closure: {name: calculation dict}  (includes pulled-in internal dependencies)
          edges:   {name: [dep names]}       (only calc->calc edges)
          physical_needed: {table: set(columns)}
          unresolved: {name: [bad refs]}
        """
        calc_by_name = {c["name"]: c for c in self._all_calculations}
        closure = {}
        edges = {}
        physical_needed = {}
        unresolved = {}

        queue = list(measure_names)
        while queue:
            name = queue.pop()
            if name in closure:
                continue
            calculation = calc_by_name.get(name)
            if not calculation:
                unresolved[name] = ["calculation not found in workbook"]
                continue

            closure[name] = calculation
            physical, calc_deps, bad = self._categorize_dependencies(calculation)

            edges[name] = calc_deps
            if bad:
                unresolved[name] = bad

            for p in physical:
                physical_needed.setdefault(p["table"], set()).add(p["column"])

            for dep_name in calc_deps:
                queue.append(dep_name)

        return closure, edges, physical_needed, unresolved

    def topo_order(self, edges: dict[str, list[str]]):
        """Kahn's algorithm; deps come before dependents. Raises on cycles."""
        visited, order, in_progress = {}, [], set()

        def visit(node):
            if node in visited:
                return
            if node in in_progress:
                raise ValueError(f"Circular KPI dependency detected at '{node}'")
            in_progress.add(node)
            for dep in edges.get(node, []):
                if dep in edges:  # only walk into nodes we actually resolved
                    visit(dep)
            in_progress.discard(node)
            visited[node] = True
            order.append(node)

        for node in edges:
            visit(node)
        return order

    def generate_shared_dummy_data(self, physical_needed: dict[str, set], row_count: int = 6):
        """One LLM call to generate consistent dummy rows for every table referenced
        anywhere in the dependency closure, so all KPIs compute off the same data."""
        if not physical_needed:
            return {}

        schema_desc = "\n".join(
            f"TABLE {table}: columns = {sorted(cols)}"
            for table, cols in physical_needed.items()
        )
        prompt = f"""
Generate {row_count} rows of realistic sample data for EACH of these tables:
{schema_desc}

For numeric columns include at least one zero and one null/missing value across
the rows, to exercise edge cases like division by zero. Keep row counts
consistent within a table.

Return ONLY JSON of this shape:
{{ "TableName": [ {{...}}, ... ], "OtherTableName": [ {{...}}, ... ] }}
"""
        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You are a precise sample-data generator. Output only the requested JSON."},
                {"role": "user", "content": prompt}
            ]
        )
        return json.loads(response.choices[0].message.content.strip())

    def validate_kpi_node(self, name, calculation, dax_expression, physical_deps,
                           calc_dep_results, shared_data, row_count):
        """Compute+compare one KPI. calc_dep_results = {dep_name: {'tableau_result':..,'powerbi_result':..}}"""
        relevant_tables = sorted({d["table"] for d in physical_deps})
        relevant_data = {t: shared_data.get(t, []) for t in relevant_tables} if relevant_tables else {}

        known_values_text = "\n".join(
            f'- "{dep}" -> Tableau side value: {calc_dep_results[dep]["tableau_result"]!r}, '
            f'Power BI side value: {calc_dep_results[dep]["powerbi_result"]!r}'
            for dep in calc_dep_results
        ) or "- none"

        prompt = f"""
You are validating a Tableau-to-Power BI KPI conversion for "{name}".

TABLEAU FORMULA:
{calculation["formula"]}

POWER BI DAX MEASURE:
{dax_expression}

SAMPLE DATA (use as-is, do not regenerate):
{json.dumps(relevant_data)}

ALREADY-VALIDATED DEPENDENCY VALUES (substitute these in place of the
corresponding [Field]/measure references - use the Tableau-side value when
evaluating the Tableau formula, and the Power BI-side value when evaluating
the DAX measure; do not recompute the dependencies yourself):
{known_values_text}

Compute:
  (a) the Tableau formula's result using the sample data + Tableau-side dependency values
  (b) the DAX measure's result using the sample data + Power BI-side dependency values
Round numeric results to 4 decimal places; treat values within 0.0001 as equal.

Return ONLY JSON of this exact shape:
{{
  "tableau_result": "<value>",
  "powerbi_result": "<value>",
  "match": true|false,
  "explanation": "<1-3 sentences on why they match or differ>"
}}
"""
        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You are a precise calculation engine. Output only the requested JSON."},
                {"role": "user", "content": prompt}
            ]
        )
        return json.loads(response.choices[0].message.content.strip())

    def validate_measures(self, measures: list[dict], row_count: int = 6):
        requested_names = [m["name"] for m in measures]
        dax_by_name = {m["name"]: m["expression"] for m in measures}

        closure, edges, physical_needed, unresolved = self.build_validation_plan(requested_names)

        try:
            order = self.topo_order(edges)
        except ValueError as exc:
            return [{"name": n, "status": "error", "explanation": str(exc)} for n in requested_names]

        shared_data = self.generate_shared_dummy_data(physical_needed, row_count)

        computed: dict[str, dict] = {}   # name -> {"tableau_result":.., "powerbi_result":..}
        results = []

        for name in order:
            calculation = closure[name]
            is_requested = name in dax_by_name
            physical, calc_deps, bad_refs = self._categorize_dependencies(calculation)

            if bad_refs:
                results.append({
                    "name": name, "status": "skipped", "requested": is_requested,
                    "explanation": f"Unresolved reference(s): {bad_refs}"
                })
                continue

            missing_dep = next((d for d in calc_deps if d not in computed), None)
            if missing_dep:
                results.append({
                    "name": name, "status": "skipped", "requested": is_requested,
                    "explanation": f"Dependency '{missing_dep}' could not be validated (missing or errored)."
                })
                continue

            dax_expression = dax_by_name.get(name)
            if dax_expression is None:
                results.append({
                    "name": name, "status": "skipped", "requested": is_requested,
                    "explanation": "No DAX expression supplied for this dependency (likely removed by a KPI-suggestion remap)."
                })
                continue

            calc_dep_results = {d: computed[d] for d in calc_deps}

            try:
                comparison = self.validate_kpi_node(
                    name, calculation, dax_expression, physical,
                    calc_dep_results, shared_data, row_count
                )
                computed[name] = {
                    "tableau_result": comparison.get("tableau_result"),
                    "powerbi_result": comparison.get("powerbi_result"),
                }
                results.append({
                    "name": name,
                    "status": "validated",
                    "requested": is_requested,
                    "level": "dependent" if calc_deps else "independent",
                    "depends_on": calc_deps,
                    "tableau_formula": calculation["formula"],
                    "dax_expression": dax_expression,
                    "tableau_result": comparison.get("tableau_result"),
                    "powerbi_result": comparison.get("powerbi_result"),
                    "match": comparison.get("match"),
                    "explanation": comparison.get("explanation"),
                })
            except Exception as exc:
                results.append({
                    "name": name, "status": "error", "requested": is_requested,
                    "explanation": f"Validation failed: {exc}"
                })

        for name, refs in unresolved.items():
            if name not in closure:
                results.append({
                    "name": name, "status": "skipped", "requested": name in dax_by_name,
                    "explanation": f"Could not resolve: {refs}"
                })

        return results


# ============================================================
# API ENDPOINTS
# ============================================================

# @app.post("/parse/{folder_name}")
# def parse_twbx(folder_name: str):
#     try:
#         parser = TWBXMetadataParser()
#         result = parser.execute(folder_name)
#         return result
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

@app.post("/parse/{folder_name}")
def parse_twbx(
    folder_name: str,
    suggestions: KpiSuggestion | None = None,
):
    """
    Parse TWBX → modelSchema.
    Optional JSON body for migrate-with-suggestions:
      { "remap": {"Performance": "Production Efficiency"}, "remove": ["Performance"] }
    Omit body (or send null) for migrate-without-suggestions.
    """
    try:
        parser = TWBXMetadataParser()
        result = parser.execute(folder_name, suggestions=suggestions)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/validate/{folder_name}")
def validate_twbx(folder_name: str, request: ValidateRequest):
    """
    Validate converted KPIs by generating shared dummy data and asking the LLM
    to compute the Tableau and DAX results from that data, flagging mismatches.

    Independent KPIs (physical-column deps only) are validated first; KPIs that
    depend on other calculated fields/measures are validated afterward, reusing
    the already-validated dependency values instead of recomputing them.

    Pass the "measures" array from /parse's Measures1 table as the request body:
      { "measures": [ {...}, {...} ], "row_count": 6 }
    """
    try:
        parser = TWBXMetadataParser()
        parser.parse_calculations_and_schema(folder_name)
        results = parser.validate_measures(request.measures, row_count=request.row_count)

        requested_results = [r for r in results if r.get("requested")]
        return {
            "folder_name": folder_name,
            "total_kpis": len(requested_results),
            "validated": sum(1 for r in requested_results if r["status"] == "validated"),
            "matches": sum(1 for r in requested_results if r.get("match") is True),
            "mismatches": sum(1 for r in requested_results if r.get("match") is False),
            "skipped": sum(1 for r in requested_results if r["status"] == "skipped"),
            "errors": sum(1 for r in requested_results if r["status"] == "error"),
            "results": results,  # includes internal (non-requested) dependencies too, for traceability
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/test/apply-suggestions")
def test_apply_suggestions(
    measures: list[dict],
    suggestions: KpiSuggestion | None = None,
):
    """Unit-test helper: apply suggestions to a measures list only."""
    result = apply_kpi_suggestions_to_measures(measures, suggestions)
    return {
        "input_count": len(measures),
        "output_count": len(result),
        "measure_names": [m.get("name") for m in result],
        "measures": result,
    }
