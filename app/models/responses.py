# Copyright 2024
# Directory: yt-rag/app/models/responses.py

"""
Response models for the RAG API endpoints.
"""

from typing import List, Literal
from pydantic import BaseModel, Field


class SeedResponse(BaseModel):
    """Response model for the /seed endpoint."""
    inserted: int = Field(..., description="Number of chunks successfully inserted")
    removed: int = Field(..., description="Number of chunks deleted because this seed didn't include them")


class DebugInfo(BaseModel):
    """Debug information for RAG responses."""
    top_doc_ids: List[str] = Field(..., description="IDs of retrieved chunks")
    latency_ms: int = Field(..., description="Total processing time in milliseconds")
    answer_mode: Literal["generated", "extractive", "no_results", "error"] = Field(
        ...,
        description=(
            "generated: the language model answered; extractive: the model was unavailable, "
            "so retrieved passages are returned; no_results: nothing was retrieved; "
            "error: answering failed before the model was called"
        ),
    )


class Source(BaseModel):
    """The passage behind one citation."""
    chunk_id: str = Field(..., description="The cited chunk's ID")
    title: str = Field(..., description="Title of the document the chunk came from, or the chunk ID")
    text: str = Field(..., description="The passage the answer was built from")


class AnswerResponse(BaseModel):
    """Response model for the /answer endpoint."""
    text: str = Field(..., description="Generated answer with inline citations")
    citations: List[str] = Field(..., description="List of chunk IDs used as sources")
    sources: List[Source] = Field(
        default_factory=list, description="One entry per citation, in the same order"
    )
    debug: DebugInfo = Field(..., description="Debug information")


class HealthResponse(BaseModel):
    """Response model for the /healthz endpoint."""
    status: str = Field(..., description="Health status")
    database_connected: bool = Field(..., description="Database connection status")


class ErrorResponse(BaseModel):
    """Standard error response model."""
    error: str = Field(..., description="Error message")
    detail: str = Field(..., description="Detailed error information")
