"""Profile schemas — every field is user-editable."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str
    updated_at: datetime
    preferred_fields: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    research_interests: list[str] = Field(default_factory=list)
    preferred_keywords: list[str] = Field(default_factory=list)
    excluded_keywords: list[str] = Field(default_factory=list)
    degrees: list[str] = Field(default_factory=list)
    degree_level: str | None = None
    gpa: float | None = None
    graduation_year: int | None = None
    years_experience: float = 0.0
    desired_program_types: list[str] = Field(default_factory=list)
    desired_job_types: list[str] = Field(default_factory=list)
    funding_preference: str = "any"
    preferred_countries: list[str] = Field(default_factory=list)
    excluded_countries: list[str] = Field(default_factory=list)
    max_tuition: float | None = None
    desired_salary: float | None = None
    willingness_to_relocate: bool = True
    remote_preference: str = "any"
    nationality: str | None = None
    current_country: str | None = None
    languages: list[str] = Field(default_factory=list)
    ielts_score: float | None = None
    toefl_score: float | None = None
    gre_status: str | None = None


class ProfileUpdate(BaseModel):
    """Partial update: only provided fields change."""

    display_name: str | None = Field(default=None, max_length=120)
    preferred_fields: list[str] | None = None
    skills: list[str] | None = None
    research_interests: list[str] | None = None
    preferred_keywords: list[str] | None = None
    excluded_keywords: list[str] | None = None
    degrees: list[str] | None = None
    degree_level: str | None = Field(default=None, max_length=40)
    gpa: float | None = Field(default=None, ge=0, le=5)
    graduation_year: int | None = Field(default=None, ge=1950, le=2100)
    years_experience: float | None = Field(default=None, ge=0, le=60)
    desired_program_types: list[str] | None = None
    desired_job_types: list[str] | None = None
    funding_preference: str | None = Field(default=None, max_length=30)
    preferred_countries: list[str] | None = None
    excluded_countries: list[str] | None = None
    max_tuition: float | None = Field(default=None, ge=0)
    desired_salary: float | None = Field(default=None, ge=0)
    willingness_to_relocate: bool | None = None
    remote_preference: str | None = Field(default=None, max_length=20)
    nationality: str | None = Field(default=None, max_length=80)
    current_country: str | None = Field(default=None, max_length=80)
    languages: list[str] | None = None
    ielts_score: float | None = Field(default=None, ge=0, le=9.0)
    toefl_score: float | None = Field(default=None, ge=0, le=120)
    gre_status: str | None = Field(default=None, max_length=30)

    @field_validator(
        "preferred_fields",
        "skills",
        "research_interests",
        "preferred_keywords",
        "excluded_keywords",
        "degrees",
        "desired_program_types",
        "desired_job_types",
        "preferred_countries",
        "excluded_countries",
        "languages",
    )
    @classmethod
    def _clean_lists(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item).strip()
            key = text.lower()
            if text and key not in seen:
                seen.add(key)
                cleaned.append(text)
        return cleaned


__all__ = ["ProfileRead", "ProfileUpdate"]
