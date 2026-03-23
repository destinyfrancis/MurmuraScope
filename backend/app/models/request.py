from __future__ import annotations

import ipaddress
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

# B2B scenario keywords that trigger auto-generation when company_count is 0
_B2B_SCENARIO_KEYWORDS: frozenset[str] = frozenset({"b2b", "trade", "enterprise", "supply_chain"})


class GraphBuildRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenario_type: Literal[
        "property",
        "emigration",
        "fertility",
        "career",
        "education",
        "b2b",
        "macro",
    ]
    seed_text: str = ""
    upload_files: list[str] | None = None
    auto_inject_hk_data: bool = True


class FamilyMember(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    age: int
    sex: Literal["M", "F"]
    occupation: str | None = None
    monthly_income: int | None = None
    education_level: str | None = None


class CRMCustomer(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    age_range: str | None = None
    district: str | None = None
    spending_level: str | None = None
    preferences: list[str] = []


class ScheduledShock(BaseModel):
    model_config = ConfigDict(frozen=True)

    round_number: int
    shock_type: str
    description: str
    post_content: str = ""
    parameters: dict = {}
    macro_effects: dict[str, float] | None = None


class SimulationCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    graph_id: str
    scenario_type: str
    agent_count: int = 300
    agent_distribution: dict | None = None
    family_members: list[FamilyMember] | None = None
    crm_data: list[CRMCustomer] | None = None
    round_count: int = 40
    macro_scenario_id: str | None = None
    shocks: list[ScheduledShock] = []
    platforms: dict = {"facebook": True, "instagram": True}
    llm_provider: str = "openrouter"
    company_count: int = Field(default=0, ge=0, description="Number of B2B company agents to generate (0 = none)")
    domain_pack_id: str = Field(default="hk_city", description="Domain pack to use for this simulation")
    # BYOK (Bring Your Own Key) fields
    api_key: str | None = Field(default=None, description="User-provided LLM API key (encrypted at rest)")
    llm_model: str | None = Field(default=None, description="LLM model override (e.g. 'gpt-4o')")
    llm_base_url: str | None = Field(default=None, description="Custom LLM endpoint (e.g. self-hosted vLLM)")
    # Preset selection
    preset: str | None = Field(default=None, description="Simulation preset: fast/standard/deep/large/massive/custom")

    @field_validator("llm_base_url")
    @classmethod
    def validate_llm_base_url(cls, v: str | None) -> str | None:
        if v is None:
            return v
        parsed = urlparse(v)
        if parsed.scheme != "https":
            raise ValueError("llm_base_url must use https://")
        hostname = parsed.hostname or ""
        if hostname in ("localhost", "0.0.0.0", ""):
            raise ValueError("llm_base_url cannot target localhost")
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                raise ValueError("llm_base_url cannot target private/loopback addresses")
        except ValueError as exc:
            # Re-raise only our own validation errors; ignore AddressValueError for domain names
            if "llm_base_url" in str(exc):
                raise
        return v


class SimulationStartRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str


class ReportGenerateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    report_type: str = "full"
    focus_areas: list[str] = []
    scenario_question: str | None = None  # "如果X發生，Y會怎樣？"


class ReportChatRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    message: str
    agent_id: int | None = None


class AgentInterviewRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    agent_id: int | str  # int for HK agents, str for kg_driven agents
    question: str


class ConfigSuggestRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_query: str
    processed_seed_summary: str | None = None


class BranchRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    fork_round: int | None = None  # Round number to fork from (None = fork entire session)
    label: str = ""  # User-friendly label for the branch
    shock_overrides: list[dict] | None = None  # Different shocks for the branch
