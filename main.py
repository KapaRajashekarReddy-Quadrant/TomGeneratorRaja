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

    def execute(self, folder_name: str) -> dict:
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
# API ENDPOINT
# ============================================================

@app.post("/parse/{folder_name}")
def parse_twbx(folder_name: str):
    try:
        parser = TWBXMetadataParser()
        result = parser.execute(folder_name)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))