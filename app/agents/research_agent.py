import asyncio
import json
import sqlite3
import unicodedata
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from app.config import get_llm
from app.state import OrchestratorState


# Datos ficticios para la demostración.
DEMO_SALES = [
    ("Llaveros", 50, 1300.0),
    ("Miniaturas", 12, 4500.0),
    ("Dummys", 8, 6500.0),
]


def normalize_text(text: str) -> str:
    """Convierte a minúsculas y elimina acentos."""
    normalized = unicodedata.normalize("NFD", text.lower())

    return "".join(
        character
        for character in normalized
        if unicodedata.category(character) != "Mn"
    )


def search_sales(query: str) -> list[dict[str, Any]]:
    """Consulta ventas ficticias en SQLite."""
    normalized_query = normalize_text(query)

    aliases = {
        "Llaveros": ("llavero",),
        "Miniaturas": ("miniatura",),
        "Dummys": ("dummy", "dummys", "dummies"),
    }

    selected_products = [
        product
        for product, keywords in aliases.items()
        if any(keyword in normalized_query for keyword in keywords)
    ]

    if not selected_products and any(
        keyword in normalized_query
        for keyword in ("venta", "producto", "facturacion", "ingreso")
    ):
        selected_products = list(aliases)

    if not selected_products:
        return []

    with sqlite3.connect(":memory:") as connection:
        connection.execute(
            """
            CREATE TABLE sales (
                product TEXT PRIMARY KEY,
                units INTEGER NOT NULL,
                unit_price REAL NOT NULL
            )
            """
        )

        connection.executemany(
            "INSERT INTO sales VALUES (?, ?, ?)",
            DEMO_SALES,
        )

        placeholders = ", ".join("?" for _ in selected_products)

        rows = connection.execute(
            f"""
            SELECT product, units, unit_price
            FROM sales
            WHERE product IN ({placeholders})
            ORDER BY product
            """,
            selected_products,
        ).fetchall()

    return [
        {
            "product": product,
            "units": units,
            "unit_price": unit_price,
            "currency": "ARS",
            "source": "SQLite: tabla sales (datos ficticios)",
        }
        for product, units, unit_price in rows
    ]


async def research_agent(
    state: OrchestratorState,
    config: RunnableConfig,
) -> dict[str, Any]:
    """Recupera datos con una herramienta y un modelo de Groq."""
    retrieved_records: dict[str, dict[str, Any]] = {}
    tool_calls: list[str] = []

    @tool
    async def search_sales_database(query: str) -> str:
        """Consulta ventas ficticias de llaveros, miniaturas y dummys.

        Usá los nombres de los productos solicitados.
        Para consultar todo el catálogo, usá:
        'ventas de todos los productos'.
        """
        # SQLite se ejecuta en otro hilo para no bloquear la API.
        records = await asyncio.to_thread(search_sales, query)

        for record in records:
            retrieved_records[record["product"]] = record

        tool_calls.append(query)

        return json.dumps(records, ensure_ascii=False)

    agent = create_react_agent(
        model=get_llm(),
        tools=[search_sales_database],
        prompt=(
            "Sos un investigador de ventas de una base SQLite "
            "de demostración. El catálogo contiene llaveros, "
            "miniaturas y dummys. "
            "Usá search_sales_database para recuperar los datos. "
            "Consultá solo los productos solicitados, o todo el "
            "catálogo si el pedido es general. "
            "No inventes productos, cantidades, precios ni fuentes. "
            "Si no hay datos, explicá la limitación. "
            "No calcules facturación: eso corresponde al analista. "
            "Respondé en español, indicá la fuente y aclarа que "
            "los datos son ficticios."
        ),
    )

    instruction = (
        f"Solicitud del usuario: {state['user_query']}\n"
        "Observaciones del supervisor: "
        f"{state.get('validation_feedback', '')}"
    )

    # Conserva la configuración de trazas del grafo principal.
    agent_config = {
        **config,
        "recursion_limit": 12,
    }

    response = await agent.ainvoke(
        {"messages": [HumanMessage(content=instruction)]},
        config=agent_config,
    )

    # Si el modelo omitió la herramienta, el worker registrará
    # el trabajo como FAILED cuando implementemos ese componente.
    if not tool_calls:
        raise RuntimeError(
            "El investigador no utilizó la herramienta de búsqueda."
        )

    content = response["messages"][-1].content
    summary = (
        content
        if isinstance(content, str)
        else json.dumps(content, ensure_ascii=False)
    )

    return {
        "research_data": list(retrieved_records.values()),
        "research_summary": summary,
        "analysis_results": {},
        "analysis_summary": "",
        "task_completed": False,
        "contributions": [
            *state.get("contributions", []),
            {
                "agent": "researcher",
                "tool": "search_sales_database",
                "summary": summary,
            },
        ],
        "messages": [
            AIMessage(content=summary, name="researcher")
        ],
        "steps": state.get("steps", 0) + 1,
    }