"""Shared enums used across persistence, services, and API schemas."""

from __future__ import annotations

import enum


class OpportunityType(str, enum.Enum):
    SCHOLARSHIP = "scholarship"
    MASTERS_PROGRAM = "masters_program"
    PHD_PROGRAM = "phd_program"
    FUNDED_PROGRAM = "funded_program"
    RESEARCH_POSITION = "research_position"
    GRADUATE_ASSISTANTSHIP = "graduate_assistantship"
    FELLOWSHIP = "fellowship"
    INTERNSHIP = "internship"
    INDUSTRY_JOB = "industry_job"
    ACADEMIC_JOB = "academic_job"
    OTHER = "other"


class FundingType(str, enum.Enum):
    FULL = "full"  # fully funded (tuition + living)
    PARTIAL = "partial"  # partial scholarship / tuition waiver
    SELF = "self"  # self-funded / tuition-only
    PAID_POSITION = "paid"  # salary-carrying job/RA/TA
    UNKNOWN = "unknown"


class DegreeLevel(str, enum.Enum):
    NONE = "none"
    BACHELORS = "bachelors"
    MASTERS = "masters"
    DOCTORATE = "doctorate"
    ANY = "any"
    UNKNOWN = "unknown"


class FreshnessStatus(str, enum.Enum):
    DISCOVERED = "discovered"
    UPDATED = "updated"
    VERIFIED = "verified"
    EXPIRED = "expired"
    STALE = "stale"
    ARCHIVED = "archived"


class ApplicationStatus(str, enum.Enum):
    DISCOVERED = "discovered"
    INTERESTED = "interested"
    SAVED = "saved"
    PREPARING = "preparing"
    APPLIED = "applied"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    ACCEPTED = "accepted"
    IGNORED = "ignored"


class SourceCategory(str, enum.Enum):
    SCHOLARSHIP_DB = "scholarship_db"
    UNIVERSITY = "university"
    ACADEMIC_JOBS = "academic_jobs"
    RESEARCH = "research"
    INDUSTRY_JOBS = "industry_jobs"
    INTERNSHIPS = "internships"
    MANUAL = "manual"


class SourceStatus(str, enum.Enum):
    IDLE = "idle"
    RUNNING = "running"
    OK = "ok"
    ERROR = "error"
    DISABLED = "disabled"


class TaxonomyKind(str, enum.Enum):
    FIELD = "field"
    SKILL = "skill"
    SYNONYM = "synonym"
    COUNTRY = "country"


class SortField(str, enum.Enum):
    RELEVANCE = "relevance"
    DEADLINE = "deadline"
    NEWEST = "newest"
    FUNDING = "funding"
    TUITION = "tuition"
    SALARY = "salary"


__all__ = [
    "ApplicationStatus",
    "DegreeLevel",
    "FreshnessStatus",
    "FundingType",
    "OpportunityType",
    "SortField",
    "SourceCategory",
    "SourceStatus",
    "TaxonomyKind",
]