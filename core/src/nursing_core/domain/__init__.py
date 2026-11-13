"""Domain types shared by the pipeline, the API, the MCP server and the evals.

Every model is frozen, refuses unknown fields and never shows its input in a validation error
(an input can be note text or a name), and every datetime is timezone-aware.
"""

from pydantic import BaseModel, ConfigDict


class DomainModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
