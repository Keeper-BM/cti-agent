"""Authenticated development examples, separate from production analysis endpoints."""

from fastapi import APIRouter

from backend.examples.assessment import AssessmentExample, load_assessment_example

router = APIRouter(prefix="/examples", tags=["development examples"])


@router.get("/assessment", response_model=AssessmentExample)
def assessment_example():
    return load_assessment_example()
