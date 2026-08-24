# from generator.utils import extract_worksheets, extract_columns

# def generate_dataset_model(metadata: dict) -> dict:
#     worksheets = extract_worksheets(metadata)

#     if not worksheets:
#         raise ValueError("❌ No worksheets available for dataset generation")

#     # Use first worksheet to infer schema (safe default)
#     columns = extract_columns(worksheets[0])

#     if not columns:
#         raise ValueError("❌ No columns found in first worksheet")

#     return {
#         "name": "AutoDataset",
#         "compatibilityLevel": 1601,
#         "model": {
#             "culture": "en-US",
#             "tables": [
#                 {
#                     "name": "MainTable",
#                     "columns": [
#                         {
#                             "name": col,
#                             "dataType": "string"
#                         }
#                         for col in columns
#                     ],
#                     "partitions": []
#                 }
#             ]
#         }
#     }


def generate_dataset_model(metadata: dict) -> dict:
    worksheets = metadata.get("worksheets", [])
    tables = []
    for ws in worksheets:
        table_name = ws.get("name", "Table")
        columns = ws.get("columns", []) or ws.get("fields", [])
        table = {
            "name": table_name,
            "columns": [{"name": col, "dataType": "string"} for col in columns]
        }
        tables.append(table)
    return {"tables": tables}
