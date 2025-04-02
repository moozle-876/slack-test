import os

from dotenv import load_dotenv
from potpie_service import PotpieAPIClient

load_dotenv()

potpie_host = os.getenv("POTPIE_HOST") or "http://localhost:8001"
potpie_client = PotpieAPIClient(potpie_host)

potpie_token = os.getenv("POTPIE_API_TOKEN") or ""

res = potpie_client.fetch_agents(potpie_token)
print(f"res: {res}")
