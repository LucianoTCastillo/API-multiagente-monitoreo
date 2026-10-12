from typing import Any, Literal

from pydantic import BaseModel, Field, StrictBool, field_validator


JobStatus = Literal[
    "PENDING",
    "RUNNING",
    "WAITING_APPROVAL",
    "DONE",
    "REJECTED",
    "FAILED",
]


class TaskRequest(BaseModel):
    """Datos necesarios para crear una tarea."""

    user_query: str = Field(min_length=1, max_length=4000)
    requires_approval: StrictBool = False

    @field_validator("user_query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("La consulta no puede estar vacía.")

        return value


class TaskCreated(BaseModel):
    """Respuesta inmediata al recibir una tarea."""

    job_id: str
    status: JobStatus
    status_url: str


class ApprovalRequest(BaseModel):
    """Decisión humana para una tarea pausada."""

    approved: StrictBool


class TaskStatusResponse(BaseModel):
    """Estado y resultado de un trabajo."""

    job_id: str
    status: JobStatus
    user_query: str
    created_at: str
    updated_at: str
    final_answer: str = ""
    error: str | None = None
    approval_details: dict[str, Any] | None = None
    execution_seconds: float = 0.0