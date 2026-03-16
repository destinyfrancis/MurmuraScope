from pydantic import BaseModel, ConfigDict


class APIResponse(BaseModel):
    success: bool
    data: dict | list | None = None
    error: str | None = None
    meta: dict | None = None


class GraphBuildResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    graph_id: str
    node_count: int
    edge_count: int
    entity_types: list[str]
    relation_types: list[str]


class SimulationCreateResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    agent_count: int
    round_count: int
    status: str
    estimated_cost_usd: float


class SimulationProgressUpdate(BaseModel):
    session_id: str
    current_round: int
    total_rounds: int
    status: str
    events_count: int
    latest_posts: list[dict] = []
    graph_updates: list[dict] = []


class ReportResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    report_id: str
    title: str
    content_markdown: str
    summary: str
    key_findings: list[str]
    charts_data: dict | None = None


class AgentProfileResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    agent_type: str
    age: int
    sex: str
    district: str
    occupation: str
    income_bracket: str
    education_level: str
    personality: dict


class DataDashboardResponse(BaseModel):
    population: dict
    economy: dict
    property_market: dict
    employment: dict
    latest_update: str
