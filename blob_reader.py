


import json
import os
from azure.storage.blob import BlobServiceClient
from urllib.parse import unquote, urlparse

def read_metadata_from_blob(blob_path: str) -> dict:
    """
    blob_path can be:
    - parsed/demoformat.json
    - OR full blob URL
    """

    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    container = os.getenv("BLOB_CONTAINER")


    if not conn_str or not container:
        raise RuntimeError("Azure Blob configuration missing")

    blob_service = BlobServiceClient.from_connection_string(conn_str)

    # If full URL is passed → extract blob name
    if blob_path.startswith("https://"):
        parsed = urlparse(blob_path)
        blob_name = unquote(parsed.path.split(container + "/")[-1])
    else:
        blob_name = blob_path

    blob_client = blob_service.get_blob_client(
        container=container,
        blob=blob_name
    )

    data = blob_client.download_blob().readall()
    return json.loads(data)


def extract_worksheets(metadata: dict) -> list:
    if "worksheets" in metadata:
        ws = metadata["worksheets"]
        if isinstance(ws, list):
            return ws
        if isinstance(ws, dict):
            return ws.get("worksheet", [])
    if "sheets" in metadata:
        return metadata["sheets"]
    if "workbook" in metadata:
        return metadata["workbook"].get("worksheets", [])
    raise ValueError("No worksheets found in metadata")
