"""API request/response schemas.

FastAPI uses these to validate incoming JSON, to check what we send back, and
to generate the interactive docs at /docs.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.analytics import Summary
from app.resolver import Kind


class AnalyzeRequest(BaseModel):
    repo_url: str = Field(max_length=300, examples=["https://github.com/pallets/click"])
    include_external: bool = Field(
        default=False, description="Also return stdlib / third-party library nodes"
    )


class NodeData(BaseModel):
    id: str = Field(description="Dotted module name, or library name for externals")
    label: str
    package: str
    path: str | None = Field(description="Repo-relative file path; null for externals")
    loc: int
    kind: Kind
    is_external: bool
    is_package: bool
    parse_error: str | None
    in_degree: int
    out_degree: int
    pagerank: float
    pagerank_rank: int | None
    community: int | None = Field(description="null for externals and isolated modules")
    in_cycle: bool
    scc_id: int | None = Field(description="Which cycle group the module belongs to, if any")


class EdgeData(BaseModel):
    id: str
    source: str = Field(description="The importing module")
    target: str = Field(description="The imported module or library")
    weight: int
    kind: Kind
    type_only: bool = Field(description="Only imported under `if TYPE_CHECKING:`")
    in_cycle: bool


class CyNode(BaseModel):
    data: NodeData


class CyEdge(BaseModel):
    data: EdgeData


class GraphResponse(BaseModel):
    repo: str
    commit_sha: str
    cached: bool
    summary: Summary
    nodes: list[CyNode]
    edges: list[CyEdge]


class ErrorResponse(BaseModel):
    detail: str
