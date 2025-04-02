from typing import List
from pydantic import BaseModel
import aiohttp
from typing import List, Union

from schema import Agent, Project


class Err(BaseModel):
    message: str
    status_code: int = -1


class PotpieAPIClient:
    def __init__(self, base_url: str):
        self.base_url = base_url

    async def fetch_projects(self, potpie_token: str) -> Union[List["Project"], "Err"]:
        url = f"{self.base_url}/api/v2/projects/list"
        # Set the headers
        headers = {
            "accept": "application/json",
            "Content-Type": "application/json",
            "x-api-key": potpie_token,
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                # Check for successful response
                if response.status == 200:
                    res = await response.json()
                    if not isinstance(res, list):
                        return Err(message="invalid object received")
                    return [
                        Project(
                            id=project["id"],
                            name=project["repo_name"],
                            status=project["status"],
                        )
                        for project in res
                    ]
                else:
                    return Err(
                        message=await response.text(), status_code=response.status
                    )

    async def fetch_agents(self, potpie_token: str) -> Union[List["Agent"], "Err"]:
        url = f"{self.base_url}/api/v2/list-available-agents"
        # Set the headers
        headers = {
            "accept": "application/json",
            "Content-Type": "application/json",
            "x-api-key": potpie_token,
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                # Check for successful response
                if response.status == 200:
                    res = await response.json()
                    if not isinstance(res, list):
                        return Err(message="invalid object received")
                    return [
                        Agent(id=agent["id"], name=agent["name"], type=agent["status"])
                        for agent in res
                    ]
                else:
                    return Err(
                        message=await response.text(), status_code=response.status
                    )

    async def create_conversation(
        self, potpie_token: str, project_id: str, agent_id: str
    ):
        url = f"{self.base_url}/api/v2/conversations/"
        # Prepare the payload
        payload = {
            "project_ids": [project_id],
            "agent_ids": [agent_id],
        }
        # Set the headers
        headers = {
            "accept": "application/json",
            "Content-Type": "application/json",
            "x-api-key": potpie_token,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                # Check for successful response
                if response.status == 200:
                    data = await response.json()
                    return str(data["conversation_id"])
                else:
                    return Err(
                        message=await response.text(), status_code=response.status
                    )

    async def send_message(self, potpie_token: str, conversation_id: str, content: str):
        url = f"{self.base_url}/api/v2/conversations/{conversation_id}/message"
        # Prepare the payload
        payload = {
            "content": content,
            "node_ids": [],  # Expecting a list of dictionaries with node_id and name
        }
        # Set the headers
        headers = {
            "accept": "application/json",
            "Content-Type": "application/json",
            "x-api-key": potpie_token,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, headers=headers, json=payload, timeout=120
            ) as response:
                # Check for successful response
                if response.status == 200:
                    data = await response.json()
                    return str(
                        data["message"]
                    )  # Return the JSON response if successful
                else:
                    return Err(
                        message=await response.text(), status_code=response.status
                    )
