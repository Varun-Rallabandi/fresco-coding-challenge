"""Output schema. Every extraction result is validated against these models."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class Span(BaseModel):
    """One piece of a set's footprint: a page and a box on it (PDF points, top-left origin)."""

    page: int = Field(description="1-based page number in the source PDF")
    bbox: tuple[float, float, float, float] = Field(description="x0, top, x1, bottom")
    lines: tuple[int, int] = Field(description="first and last line index on the page")


class Component(BaseModel):
    qty: Optional[int] = Field(None, description="null when the book leaves it blank or says 'as required'")
    description: Optional[str] = None
    catalog_number: Optional[str] = None
    mfr: Optional[str] = None
    mfr_name: Optional[str] = Field(None, description="full manufacturer name when the code is known")
    finish: Optional[str] = None
    notes: Optional[str] = None
    confidence: float = 1.0
    page: int = 0
    bbox: Optional[tuple[float, float, float, float]] = None


class HardwareSet(BaseModel):
    set_number: str
    description: Optional[str] = None
    doors: Optional[str] = None
    not_used: bool = False
    location: list[Span]
    components: list[Component] = []
    notes: Optional[str] = None
    confidence: float = 1.0
    warnings: list[str] = []


class Extraction(BaseModel):
    source_file: str
    hardware_pages: list[int]
    columns: list[dict] = Field(default_factory=list, description="how each column was classified, with its votes")
    learned_codes: dict[str, dict[str, str]] = Field(default_factory=dict)
    stats: dict = Field(default_factory=dict, description="run summary: timing, OCR pages, grounding")
    sets: list[HardwareSet]
