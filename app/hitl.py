from typing import Any, Literal

from langchain_core.messages import AIMessage
from langgraph.types import interrupt

from app.agents.research_agent import normalize_text
from app.state import OrchestratorState


# Reglas sencillas para demostrar la detección de tareas críticas.
CRITICAL_PHRASES = (
    "cambiar precio",
    "cambiar los precios",
    "modificar precio",
    "modificar los precios",
    "eliminar",
    "borrar",
    "enviar",
    "transferir",
    "comprar",
    "publicar",
)


def assess_task(state: OrchestratorState) -> dict[str, Any]:
    """Detecta si la tarea necesita aprobación humana."""
    query = normalize_text(state["user_query"])

    matches = [
        phrase
        for phrase in CRITICAL_PHRASES
        if phrase in query
    ]

    # También permite solicitar aprobación explícitamente
    # desde la API que implementaremos después.
    requires_approval = (
        state.get("requires_approval", False)
        or bool(matches)
    )

    if requires_approval:
        reason = state.get("approval_reason", "").strip()

        if not reason:
            reason = (
                "La solicitud contiene una posible acción crítica: "
                + ", ".join(matches)
                if matches
                else "Se solicitó aprobación humana para esta tarea."
            )

        return {
            "requires_approval": True,
            "approval_reason": reason,
            "approval_status": "pending",
        }

    return {
        "requires_approval": False,
        "approval_reason": "",
        "approval_status": "not_required",
    }


def human_approval(state: OrchestratorState) -> dict[str, Any]:
    """Pausa el grafo hasta recibir una decisión externa."""
    decision = interrupt({
        "job_id": state["job_id"],
        "user_query": state["user_query"],
        "reason": state["approval_reason"],
        "message": (
            "Esta tarea requiere aprobación humana para continuar "
            "con el análisis. La demostración no ejecuta acciones "
            "externas ni modifica la base de datos."
        ),
        "expected_response": {"approved": True},
    })

    if (
        not isinstance(decision, dict)
        or type(decision.get("approved")) is not bool
    ):
        raise ValueError(
            "La decisión debe contener 'approved' con valor "
            "booleano: true o false."
        )

    approved = decision["approved"]

    if approved:
        summary = "Tarea aprobada. Se continúa con el análisis."
        final_answer = ""
    else:
        summary = "Tarea rechazada. Se detuvo la ejecución."
        final_answer = (
            "La tarea fue rechazada durante la revisión humana."
        )

    return {
        "approval_status": "approved" if approved else "rejected",
        "task_completed": False,
        "final_answer": final_answer,
        "contributions": [
            *state.get("contributions", []),
            {
                "agent": "human",
                "tool": "approval",
                "summary": summary,
            },
        ],
        "messages": [
            AIMessage(content=summary, name="human_review")
        ],
    }


def route_approval(
    state: OrchestratorState,
) -> Literal["human_approval", "supervisor"]:
    """Decide si corresponde pausar o iniciar el análisis."""
    if state.get("approval_status") == "pending":
        return "human_approval"

    return "supervisor"


def route_after_approval(
    state: OrchestratorState,
) -> Literal["supervisor", "FINISH"]:
    """Continúa si se aprobó; finaliza si se rechazó."""
    if state.get("approval_status") == "approved":
        return "supervisor"

    return "FINISH"