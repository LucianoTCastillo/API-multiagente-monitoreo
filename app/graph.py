from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from app.agents.analyst_agent import analyst_agent
from app.agents.research_agent import research_agent
from app.hitl import (
    assess_task,
    human_approval,
    route_after_approval,
    route_approval,
)
from app.state import OrchestratorState
from app.supervisor import route_next, supervisor


def build_graph(checkpointer: BaseCheckpointSaver):
    """Construye el grafo con un almacenamiento de checkpoints."""
    builder = StateGraph(OrchestratorState)

    # Registra los componentes del flujo.
    builder.add_node("assess_task", assess_task)
    builder.add_node("human_approval", human_approval)
    builder.add_node("supervisor", supervisor)
    builder.add_node("researcher", research_agent)
    builder.add_node("analyst", analyst_agent)

    # Toda solicitud comienza con la evaluación de aprobación.
    builder.add_edge(START, "assess_task")

    builder.add_conditional_edges(
        "assess_task",
        route_approval,
        {
            "human_approval": "human_approval",
            "supervisor": "supervisor",
        },
    )

    # Una tarea rechazada termina sin ejecutar los agentes.
    builder.add_conditional_edges(
        "human_approval",
        route_after_approval,
        {
            "supervisor": "supervisor",
            "FINISH": END,
        },
    )

    # El supervisor decide qué especialista debe intervenir.
    builder.add_conditional_edges(
        "supervisor",
        route_next,
        {
            "researcher": "researcher",
            "analyst": "analyst",
            "FINISH": END,
        },
    )

    # Cada especialista devuelve el control al supervisor.
    builder.add_edge("researcher", "supervisor")
    builder.add_edge("analyst", "supervisor")

    return builder.compile(checkpointer=checkpointer)