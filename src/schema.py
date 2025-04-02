from pydantic import BaseModel


class Project(BaseModel):
    id: str
    name: str
    status: str


class Agent(BaseModel):
    id: str
    name: str
    type: str
