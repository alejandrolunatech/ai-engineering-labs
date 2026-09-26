"""Output contract for PR Guardian.

`ReviewResult` is what the model must produce (enforced as a JSON schema via
structured output). `ReviewRun` is what *our code* records around the model
call — the model never fills in usage or timing.
"""

from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["low", "medium", "high", "critical"]


class Finding(BaseModel):
    severity: Severity = Field(description="Impact if the defect ships.")
    file: str = Field(description="Path of the affected file, relative to the case root.")
    line: int | None = Field(description="Line number in the file, or null if not applicable.")
    issue: str = Field(description="What is wrong, stated as a concrete defect.")
    evidence: str = Field(
        description="Code, diff hunk, or test output that demonstrates the defect."
    )
    recommendation: str = Field(description="A specific fix.")


class ReviewResult(BaseModel):
    summary: str = Field(description="One or two sentences describing the change and verdict.")
    findings: list[Finding] = Field(
        description="Real defects only. An empty list is the correct answer for a clean PR."
    )


class UsageStats(BaseModel):
    requests: int
    input_tokens: int
    output_tokens: int
    total_tokens: int


class ReviewRun(BaseModel):
    case_id: str
    model: str
    elapsed_seconds: float
    usage: UsageStats
    trace_id: str | None
    result: ReviewResult
