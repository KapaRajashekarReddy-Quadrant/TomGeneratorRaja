import os
from dotenv import load_dotenv
from msal import ConfidentialClientApplication

# 🔑 LOAD ENV HERE
load_dotenv()

TENANT_ID = os.getenv("TENANT_ID")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")

if not all([TENANT_ID, CLIENT_ID, CLIENT_SECRET]):
    raise Exception(
        f"Missing auth env vars:\n"
        f"TENANT_ID={TENANT_ID}\n"
        f"CLIENT_ID={CLIENT_ID}\n"
        f"CLIENT_SECRET={'SET' if CLIENT_SECRET else None}"
    )

AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPE = ["https://analysis.windows.net/powerbi/api/.default"]

def get_access_token():
    app = ConfidentialClientApplication(
        client_id=CLIENT_ID,
        client_credential=CLIENT_SECRET,
        authority=AUTHORITY
    )

    result = app.acquire_token_for_client(scopes=SCOPE)

    if "access_token" not in result:
        raise Exception(f"Token acquisition failed: {result}")

    return result["access_token"]
