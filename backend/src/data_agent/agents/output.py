"""FinalAnswer: the only conversational exit (agent-design v3 §1)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AssetRef(BaseModel):
    id: str
    name: str
    version: int


class FinalAnswer(BaseModel):
    summary: str = Field(description="markdown 结论正文（业务语言）")
    key_findings: list[str] = Field(default_factory=list)
    numbers: dict[str, str] = Field(default_factory=dict,
                                    description="结论数值 -> 来源（run step / gate 记录），防幻觉")
    touched_assets: list[AssetRef] = Field(default_factory=list)
    followups: list[str] = Field(default_factory=list)
