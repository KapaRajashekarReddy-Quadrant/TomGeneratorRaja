# import os
# import json
# import requests

# from fastapi import FastAPI, HTTPException
# from fastapi.middleware.cors import CORSMiddleware
# from pydantic import BaseModel
# from dotenv import load_dotenv
# from msal import ConfidentialClientApplication
# from azure.storage.blob import BlobServiceClient

# # 1. IMPORT THE GENERATOR FUNCTIONS (Same as main.py)
# from blob_reader import read_metadata_from_blob, extract_worksheets
# from generator.dataset import generate_dataset_model
# from generator.visual import generate_visual
# from generator.layout import next_position

# # =========================================================
# # ENV
# # =========================================================
# load_dotenv()

# TENANT_ID = os.getenv("TENANT_ID")
# CLIENT_ID = os.getenv("CLIENT_ID")
# CLIENT_SECRET = os.getenv("CLIENT_SECRET")
# AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
# BLOB_INPUT_CONTAINER = os.getenv("BLOB_INPUT_CONTAINER")

# AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
# SCOPE = ["https://analysis.windows.net/powerbi/api/.default"]

# # =========================================================
# # APP
# # =========================================================
# app = FastAPI()

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# # =========================================================
# # MODELS
# # =========================================================
# class EmbedRequest(BaseModel):
#     workspaceId: str
#     reportId: str
#     datasetId: str

# class RuntimeVisualsRequest(BaseModel):
#     metadataBlobPath: str

# # =========================================================
# # POWER BI AUTH
# # =========================================================
# def get_access_token() -> str:
#     app_auth = ConfidentialClientApplication(
#         CLIENT_ID,
#         authority=AUTHORITY,
#         client_credential=CLIENT_SECRET
#     )
#     token = app_auth.acquire_token_for_client(scopes=SCOPE)
#     return token["access_token"]

# # =========================================================
# # API: EMBED TOKEN
# # =========================================================
# @app.post("/embed-token")
# def generate_embed_token(data: EmbedRequest):
#     try:
#         access_token = get_access_token()
#         headers = {
#             "Authorization": f"Bearer {access_token}",
#             "Content-Type": "application/json"
#         }
#         token_url = (
#             f"https://api.powerbi.com/v1.0/myorg/"
#             f"groups/{data.workspaceId}/reports/{data.reportId}/GenerateToken"
#         )
#         payload = {
#             "accessLevel": "Edit",
#             "allowSaveAs": True,
#             "datasets": [{"id": data.datasetId}]
#         }
#         token_res = requests.post(token_url, headers=headers, json=payload)
        
#         if token_res.status_code != 200:
#             raise HTTPException(
#                 status_code=token_res.status_code,
#                 detail=token_res.text
#             )
            
#         token_json = token_res.json()
#         return {
#             "embedToken": token_json["token"],
#             "embedUrl": (
#                 f"https://app.powerbi.com/reportEmbed"
#                 f"?reportId={data.reportId}"
#                 f"&groupId={data.workspaceId}"
#             ),
#             "datasetId": data.datasetId
#         }
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

# # =========================================================
# # API: GENERATE runtime_visuals (FIXED TO MATCH MAIN.PY)
# # =========================================================
# @app.post("/runtime-visuals")
# def generate_runtime_visuals(req: RuntimeVisualsRequest):
#     try:
#         # 1️⃣ Read metadata from Blob
#         metadata = read_metadata_from_blob(req.metadataBlobPath)
#         worksheets = extract_worksheets(metadata)

#         if not worksheets:
#             raise ValueError("No worksheets found in metadata")

#         # 2️⃣ Generate Dataset Model to get the correct Table Name
#         # (This matches main.py logic: Step 2)
#         dataset_model = generate_dataset_model(metadata)
        
#         # Safe extraction of table name
#         table_name = "MainTable"
#         if dataset_model.get("tables") and len(dataset_model["tables"]) > 0:
#             table_name = dataset_model["tables"][0]["name"]

#         # 3️⃣ Initialize Structure (Matches main.py logic: Step 4)
#         runtime_visuals = {
#             "dataset": {
#                 "table": table_name
#             },
#             "visuals": []
#         }

#         # 4️⃣ Iterate and Build Visuals using Generator
#         for i, ws in enumerate(worksheets):
#             # Calculate Position (Matches main.py)
#             pos = next_position(i)

#             # Generate Visual using the helper function (Matches main.py)
#             visual_json = generate_visual(ws, table_name, pos["x"], pos["y"])

#             runtime_visuals["visuals"].append(visual_json)

#         # 5️⃣ Return the exact dictionary (No wrapper status object)
#         return runtime_visuals

#     except Exception as e:
#         # Print error to console for debugging
#         print(f"Error generating visuals: {str(e)}")
#         raise HTTPException(status_code=500, detail=str(e))







# ///////////////////////////////////////new part 



# import os
# import json
# import requests
# from fastapi import FastAPI, HTTPException
# from fastapi.middleware.cors import CORSMiddleware
# from pydantic import BaseModel
# from dotenv import load_dotenv
# from msal import ConfidentialClientApplication

# # 1. IMPORT THE GENERATOR FUNCTIONS
# from blob_reader import read_metadata_from_blob, extract_worksheets
# from generator.dataset import generate_dataset_model
# from generator.visual import generate_visual
# from generator.layout import next_position

# load_dotenv()

# # ENV Config
# TENANT_ID = os.getenv("TENANT_ID")
# CLIENT_ID = os.getenv("CLIENT_ID")
# CLIENT_SECRET = os.getenv("CLIENT_SECRET")
# AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
# SCOPE = ["https://analysis.windows.net/powerbi/api/.default"]

# app = FastAPI()

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# class EmbedRequest(BaseModel):
#     workspaceId: str
#     reportId: str
#     datasetId: str

# class RuntimeVisualsRequest(BaseModel):
#     metadataBlobPath: str

# def get_access_token() -> str:
#     app_auth = ConfidentialClientApplication(
#         CLIENT_ID,
#         authority=AUTHORITY,
#         client_credential=CLIENT_SECRET
#     )
#     token = app_auth.acquire_token_for_client(scopes=SCOPE)
#     return token["access_token"]

# @app.post("/embed-token")
# def generate_embed_token(data: EmbedRequest):
#     try:
#         access_token = get_access_token()
#         headers = {
#             "Authorization": f"Bearer {access_token}",
#             "Content-Type": "application/json"
#         }
#         token_url = f"https://api.powerbi.com/v1.0/myorg/groups/{data.workspaceId}/reports/{data.reportId}/GenerateToken"
#         payload = {
#             "accessLevel": "Edit",
#             "allowSaveAs": True,
#             "datasets": [{"id": data.datasetId}]
#         }
#         token_res = requests.post(token_url, headers=headers, json=payload)
#         if token_res.status_code != 200:
#             raise HTTPException(status_code=token_res.status_code, detail=token_res.text)
#         token_json = token_res.json()
#         return {
#             "embedToken": token_json["token"],
#             "embedUrl": f"https://app.powerbi.com/reportEmbed?reportId={data.reportId}&groupId={data.workspaceId}",
#             "datasetId": data.datasetId
#         }
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))



import os
import json
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from msal import ConfidentialClientApplication

# 1. IMPORT THE GENERATOR FUNCTIONS
from blob_reader import read_metadata_from_blob, extract_worksheets
from generator.dataset import generate_dataset_model
from generator.visual import generate_visual
from generator.layout import next_position

load_dotenv()

# ENV Config
TENANT_ID = os.getenv("TENANT_ID")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPE = ["https://analysis.windows.net/powerbi/api/.default"]

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CHANGED: Added userToken to the expected JSON payload
class EmbedRequest(BaseModel):
    workspaceId: str
    reportId: str
    datasetId: str
    userToken: str 

class RuntimeVisualsRequest(BaseModel):
    metadataBlobPath: str

# KEPT EXISTING: Your original Service Principal token function
def get_access_token() -> str:
    app_auth = ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET
    )
    token = app_auth.acquire_token_for_client(scopes=SCOPE)
    return token["access_token"]

# CHANGED: We don't need OBO anymore! The token from the frontend is already valid for Power BI.
@app.post("/embed-token")
def generate_embed_token(data: EmbedRequest):
    try:
        # The userToken from sessionStorage IS your Power BI access token!
        access_token = data.userToken 
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        token_url = f"https://api.powerbi.com/v1.0/myorg/groups/{data.workspaceId}/reports/{data.reportId}/GenerateToken"
        payload = {
            "accessLevel": "Edit",
            "allowSaveAs": True,
            "datasets": [{"id": data.datasetId}]
        }
        
        # Send the request directly to Power BI using the user's token
        token_res = requests.post(token_url, headers=headers, json=payload)
        
        if token_res.status_code != 200:
            raise HTTPException(status_code=token_res.status_code, detail=token_res.text)
            
        token_json = token_res.json()
        
        return {
            "embedToken": token_json["token"],
            "embedUrl": f"https://app.powerbi.com/reportEmbed?reportId={data.reportId}&groupId={data.workspaceId}",
            "datasetId": data.datasetId
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))






# @app.post("/runtime-visuals")
# def generate_runtime_visuals(req: RuntimeVisualsRequest):
#     try:
#         # 1. Read metadata from Blob
#         metadata = read_metadata_from_blob(req.metadataBlobPath)
#         worksheets = extract_worksheets(metadata)

#         if not worksheets:
#             raise ValueError("No worksheets found in metadata")

#         runtime_visuals = {"visuals": []}

#         # 2. Iterate and Build Visuals
#         for i, ws in enumerate(worksheets):
#             # Dynamic Table Selection logic
#             current_table_name = ws.get("tableName") or ws.get("table")
            
#             if not current_table_name and ws.get("columns"):
#                 current_table_name = ws["columns"][0].get("table")
            
#             if not current_table_name:
#                 current_table_name = "fact_sales"

#             pos = next_position(i)
#             visual_json = generate_visual(ws, current_table_name, pos["x"], pos["y"])
#             runtime_visuals["visuals"].append(visual_json)

#         return runtime_visuals

#     except Exception as e:
#         print(f"Error generating visuals: {str(e)}")
#         raise HTTPException(status_code=500, detail=str(e))




@app.post("/runtime-visuals")
def generate_runtime_visuals(req: RuntimeVisualsRequest):
    try:
        # 1. Read metadata from Blob
        metadata = read_metadata_from_blob(req.metadataBlobPath)
        worksheets = extract_worksheets(metadata)
        
        # NEW: Extract dashboard mapping from metadata
        dashboards = metadata.get("dashboards", [])

        if not worksheets:
            raise ValueError("No worksheets found in metadata")

        runtime_visuals = {
            "visuals": [],
            "dashboards": dashboards  # Ensure dashboards are passed to frontend
        }

        # 2. Iterate and Build Visuals
        for i, ws in enumerate(worksheets):
            current_table_name = ws.get("tableName") or ws.get("table")
            
            if not current_table_name and ws.get("columns"):
                current_table_name = ws["columns"][0].get("table")
            
            if not current_table_name:
                current_table_name = "fact_sales"

            pos = next_position(i)
            visual_json = generate_visual(ws, current_table_name, pos["x"], pos["y"])
            runtime_visuals["visuals"].append(visual_json)

        return runtime_visuals

    except Exception as e:
        print(f"Error generating visuals: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


