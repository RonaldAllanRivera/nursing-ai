"""Domain types shared by the pipeline, the API, the MCP server and the evals.

Every model is frozen and refuses unknown fields, and every datetime is timezone-aware.
"""

from pydantic import BaseModel, ConfigDict


class DomainModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
