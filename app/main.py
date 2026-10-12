import logging
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from langgraph.checkpoint.redis.aio import AsyncRedisSaver
from redis.asyncio import Redis

from app.config import get_redis_url
from app.graph import build_graph
from app.schemas import (
    ApprovalRequest,
    TaskCreated,
    TaskRequest,
    TaskStatusResponse,
)
from app.worker import TaskWorker


logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Abre las conexiones y los workers al iniciar la API."""
    redis_url = get_redis_url()

    redis = Redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )

    try:
        await redis.ping()

        async with AsyncRedisSaver.from_conn_string(
            redis_url
        ) as checkpointer:
            await checkpointer.asetup()

            graph = build_graph(checkpointer)
            worker = TaskWorker(redis, graph, concurrency=5)

            app.state.redis = redis
            app.state.worker = worker

            await worker.start()

            try:
                yield
            finally:
                # Mantiene abiertas las conexiones mientras
                # terminan los trabajos pendientes.
                await worker.stop()

    finally:
        await redis.aclose()


app = FastAPI(
    title="API multiagente de ventas",
    description=(
        "Análisis de ventas ficticias con Groq, LangGraph, "
        "Redis y aprobación humana."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health(request: Request):
    """Comprueba la conexión con Redis."""
    try:
        await request.app.state.redis.ping()
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Redis no está disponible.",
        ) from None

    return {
        "status": "ok",
        "redis": "connected",
    }


@app.post(
    "/tasks",
    response_model=TaskCreated,
    status_code=202,
)
async def create_task(
    task: TaskRequest,
    request: Request,
):
    """Encola una tarea y devuelve su identificador."""
    worker = request.app.state.worker
    job_id = await worker.submit(task)

    return TaskCreated(
        job_id=job_id,
        status="PENDING",
        status_url=f"/tasks/{job_id}",
    )


@app.get(
    "/tasks/{job_id}",
    response_model=TaskStatusResponse,
)
async def get_task(
    job_id: UUID,
    request: Request,
):
    """Consulta el estado guardado en Redis."""
    worker = request.app.state.worker
    job = await worker.get_job(str(job_id))

    if job is None:
        raise HTTPException(
            status_code=404,
            detail="No se encontró el trabajo.",
        )

    return job


@app.post(
    "/tasks/{job_id}/approve",
    response_model=TaskCreated,
    status_code=202,
)
async def approve_task(
    job_id: UUID,
    decision: ApprovalRequest,
    request: Request,
):
    """Encola la aprobación o el rechazo de una tarea pausada."""
    worker = request.app.state.worker
    identifier = str(job_id)

    try:
        await worker.approve(
            identifier,
            approved=decision.approved,
        )
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail="No se encontró el trabajo.",
        ) from None
    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail=str(error),
        ) from None

    return TaskCreated(
        job_id=identifier,
        status="PENDING",
        status_url=f"/tasks/{identifier}",
    )