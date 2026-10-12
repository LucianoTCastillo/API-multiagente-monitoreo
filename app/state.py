from typing import Any, Literal

from langgraph.graph import MessagesState


class OrchestratorState(MessagesState):
    """Estado compartido por los agentes durante una tarea."""

    # Identificador del trabajo y solicitud del usuario.
    job_id: str
    user_query: str

    # Próximo agente elegido por el supervisor.
    next_agent: Literal["researcher", "analyst", "FINISH"]

    # Información recuperada por el investigador.
    research_data: list[dict[str, Any]]
    research_summary: str

    # Resultados del analista.
    analysis_results: dict[str, Any]
    analysis_summary: str

    # Aportes de los agentes y observaciones de validación.
    contributions: list[dict[str, str]]
    validation_feedback: str

    # Control del flujo.
    steps: int
    max_steps: int
    task_completed: bool

    # Aprobación humana para acciones críticas.
    requires_approval: bool
    approval_reason: str
    approval_status: Literal[
        "not_required",
        "pending",
        "approved",
        "rejected",
    ]

    # Respuesta final.
    final_answer: str