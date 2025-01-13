import uuid
from datetime import date, datetime
from typing import List, Optional
from pydantic import BaseModel, Field

class MLTModel(BaseModel):
    title: Optional[str] = Field(None)
    description: Optional[str] = Field(None)

class TrialModel(BaseModel):
    brief_summary: str = Field(...)
    brief_title: str = Field(...)
    condition_mesh_term: List[str] = []
    condition: List[str] = []
    detailed_description: str = Field(...)
    enrollment: int = Field(...)
    gender: str = Field(...)
    minimum_age: int = Field(...)
    nct_id: str = Field(...)
    phase: str = Field(...)
    status: str = Field(...)
    study_type: str = Field(...)
    url: str = Field(...)

    class Config:
        allow_population_by_field_name = True

class DrugModel(BaseModel):
    id: str = Field(default_factory=uuid.uuid4)
    effective_time: date = Field(default_factory=datetime.now)
    purpose: str = Field(...)

    class Config:
        allow_population_by_field_name = True
