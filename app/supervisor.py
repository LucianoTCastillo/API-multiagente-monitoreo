import asyncio
import json
from typing import Any, Literal

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from app.agents.analyst_agent import analyze_sales
from app.config import get_llm
from app.state import OrchestratorState


class SupervisorDecision(BaseModel):
    """Decisión estructurada del modelo."""

    next_agent: Literal["researcher", "analyst", "FINISH"]
    reason: str = Field(description="Motivo breve de la decisión.")
    feedback: str = Field(
        description="Corrección para el especialista, o vacío."
    )
    final_answer: str = Field(
        description="Respuesta final, o vacío si falta trabajo."
    )


def build_update(
    state: OrchestratorState,
    destination: Literal["researcher", "analyst", "FINISH"],
    reason: str,
    feedback: str = "",
    final_answer: str = "",
    completed: bool = False,
) -> dict[str, Any]:
    """Registra la decisión del supervisor."""
    summary = f"Decisión: {destination}.\nMotivo: {reason}"

    if feedback:
        summary += f"\nObservaciones: {feedback}"

    return {
        "next_agent": destination,
        "validation_feedback": feedback,
        "task_completed": completed,
        "final_answer": final_answer,
        "steps": state.get("steps", 0) + 1,
        "contributions": [
            *state.get("contributions", []),
            {
                "agent": "supervisor",
                "tool": "llm_routing_and_python_validation",
                "summary": summary,
            },
        ],
        "messages": [
            AIMessage(content=summary, name="supervisor")
        ],
    }


async def supervisor(
    state: OrchestratorState,
    config: RunnableConfig,
) -> dict[str, Any]:
    """Coordina los agentes y verifica los cálculos con Python."""
    steps = state.get("steps", 0)
    max_steps = state.get("max_steps", 12)
    contributions = state.get("contributions", [])

    research_attempts = sum(
        item.get("agent") == "researcher"
        for item in contributions
    )
    analysis_attempts = sum(
        item.get("agent") == "analyst"
        for item in contributions
    )

    if steps >= max_steps:
        raise RuntimeError(
            "Se alcanzó el límite de pasos sin completar la tarea."
        )

    data = state.get("research_data", [])
    expected = await asyncio.to_thread(analyze_sales, data)

    # Sin registros después de dos búsquedas: respuesta limitada
    # al catálogo de demostración.
    if not data and research_attempts >= 2:
        return build_update(
            state,
            destination="FINISH",
            reason="No hay registros para la consulta.",
            final_answer=(
                "No encontré datos para responder la consulta. "
                "La demostración contiene ventas ficticias "
                "de llaveros, miniaturas y dummys."
            ),
            completed=True,
        )

    if not expected["valid"] and research_attempts >= 2:
        raise RuntimeError(
            "Los datos no pasaron la validación: "
            + "; ".join(expected["errors"])
        )

    results_validated = (
        expected["valid"]
        and state.get("analysis_results", {}) == expected
        and bool(state.get("analysis_summary", "").strip())
    )

    allowed_destinations = []

    if research_attempts < 2:
        allowed_destinations.append("researcher")

    if expected["valid"] and analysis_attempts < 2:
        allowed_destinations.append("analyst")

    if results_validated:
        allowed_destinations.append("FINISH")

    if not allowed_destinations:
        raise RuntimeError(
            "Se agotaron los intentos sin obtener un análisis validado."
        )

    context = {
        "user_query": state["user_query"],
        "research_data": data,
        "research_summary": state.get("research_summary", ""),
        "analysis_results": state.get("analysis_results", {}),
        "analysis_summary": state.get("analysis_summary", ""),
        "validation_feedback": state.get("validation_feedback", ""),
        "python_validation": {
            "results_validated": results_validated,
            "errors": expected.get("errors", []),
        },
        "allowed_destinations": allowed_destinations,
    }

    model = get_llm().with_structured_output(
        SupervisorDecision,
        method="function_calling",
    )

    decision = await model.ainvoke(
        [
            SystemMessage(content=(
                "Sos el supervisor de un equipo de ventas. "
                "Elegí únicamente entre allowed_destinations. "
                "Si faltan datos, delegá al researcher. "
                "Si faltan cálculos o hay errores en la explicación, "
                "delegá al analyst con una corrección concreta. "
                "Revisá que los productos respondan a la solicitud, "
                "que los resúmenes coincidan con las cifras y que "
                "se mencione que son datos ficticios. "
                "La facturación no es ganancia. "
                "Solo finalizá cuando results_validated sea true "
                "y la explicación responda al usuario. "
                "Al finalizar, integrá los resultados en español "
                "sin inventar datos. "
                "Si delegás, dejá final_answer vacío. "
                "Tu tarea es analizar y coordinar; no afirmes haber "
                "enviado mensajes, cambiado precios ni ejecutado "
                "acciones externas."
            )),
            HumanMessage(
                content=json.dumps(context, ensure_ascii=False)
            ),
        ],
        config=config,
    )

    if decision.next_agent not in allowed_destinations:
        raise RuntimeError(
            "El supervisor eligió un destino no permitido: "
            f"{decision.next_agent}"
        )

    completed = decision.next_agent == "FINISH"

    if completed and not decision.final_answer.strip():
        raise RuntimeError(
            "El supervisor finalizó sin una respuesta."
        )

    return build_update(
        state,
        destination=decision.next_agent,
        reason=decision.reason,
        feedback="" if completed else decision.feedback,
        final_answer=decision.final_answer if completed else "",
        completed=completed,
    )


def route_next(
    state: OrchestratorState,
) -> Literal["researcher", "analyst", "FINISH"]:
    """Indica qué conexión debe seguir el grafo."""
    return state["next_agent"]