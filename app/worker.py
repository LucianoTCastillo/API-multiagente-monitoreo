import asyncio
import json
import logging
from datetime import datetime, timezone
from time import perf_counter
from typing import Any
from uuid import uuid4

from langgraph.types import Command
from redis.asyncio import Redis

from app.schemas import TaskRequest


logger = logging.getLogger(__name__)


def now_iso() -> str:
    """Fecha y hora en formato ISO."""
    return datetime.now(timezone.utc).isoformat()


class TaskWorker:
    """Ejecuta tareas en segundo plano y guarda su estado en Redis."""

    def __init__(self, redis: Redis, graph, concurrency: int = 5):
        self.redis = redis
        self.graph = graph
        self.concurrency = concurrency
        self.queue: asyncio.Queue = asyncio.Queue()
        self.workers: list[asyncio.Task] = []
        self.control_lock = asyncio.Lock()

    @staticmethod
    def job_key(job_id: str) -> str:
        return f"jobs:{job_id}"

    async def save_job(self, job: dict[str, Any]) -> None:
        job["updated_at"] = now_iso()

        await self.redis.set(
            self.job_key(job["job_id"]),
            json.dumps(job, ensure_ascii=False),
        )

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        raw = await self.redis.get(self.job_key(job_id))

        if raw is None:
            return None

        return json.loads(raw)

    async def submit(self, request: TaskRequest) -> str:
        """Guarda el trabajo y lo agrega a la cola."""
        job_id = str(uuid4())
        timestamp = now_iso()

        job = {
            "job_id": job_id,
            "status": "PENDING",
            "user_query": request.user_query,
            "requires_approval": request.requires_approval,
            "created_at": timestamp,
            "updated_at": timestamp,
            "final_answer": "",
            "error": None,
            "approval_details": None,
            "execution_seconds": 0.0,
        }

        await self.save_job(job)
        self.queue.put_nowait((job_id, None))

        return job_id

    async def approve(self, job_id: str, approved: bool) -> None:
        """Encola la decisión humana sin ejecutar el grafo en el endpoint."""
        async with self.control_lock:
            job = await self.get_job(job_id)

            if job is None:
                raise KeyError(job_id)

            if job["status"] != "WAITING_APPROVAL":
                raise ValueError(
                    "El trabajo no está esperando aprobación."
                )

            # Cambiar el estado evita encolar dos aprobaciones.
            job["status"] = "PENDING"
            job["error"] = None
            await self.save_job(job)

            self.queue.put_nowait((job_id, approved))

    async def start(self) -> None:
        """Inicia los consumidores de la cola."""
        self.workers = [
            asyncio.create_task(
                self.consume(),
                name=f"task-worker-{index}",
            )
            for index in range(self.concurrency)
        ]

    async def stop(self) -> None:
        """Espera los trabajos encolados antes de cerrar."""
        await self.queue.join()

        for worker in self.workers:
            worker.cancel()

        await asyncio.gather(
            *self.workers,
            return_exceptions=True,
        )

        self.workers.clear()

    async def consume(self) -> None:
        """Procesa trabajos; un fallo no detiene el consumidor."""
        while True:
            job_id, approved = await self.queue.get()

            try:
                await self.execute(job_id, approved)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "No se pudo procesar o guardar el trabajo %s",
                    job_id,
                )
            finally:
                self.queue.task_done()

    async def execute(
        self,
        job_id: str,
        approved: bool | None,
    ) -> None:
        """Inicia o retoma una ejecución de LangGraph."""
        job = await self.get_job(job_id)

        if job is None:
            raise KeyError(job_id)

        started = perf_counter()
        previous_seconds = job.get("execution_seconds", 0.0)

        config = {
            "configurable": {"thread_id": job_id},
            "recursion_limit": 40,
            "run_name": (
                "sales_task" if approved is None else "sales_task_resume"
            ),
            "metadata": {"job_id": job_id},
        }

        try:
            job["status"] = "RUNNING"
            await self.save_job(job)

            if approved is None:
                graph_input = {
                    "job_id": job_id,
                    "user_query": job["user_query"],
                    "messages": [],
                    "next_agent": "researcher",
                    "research_data": [],
                    "research_summary": "",
                    "analysis_results": {},
                    "analysis_summary": "",
                    "contributions": [],
                    "validation_feedback": "",
                    "steps": 0,
                    "max_steps": 12,
                    "task_completed": False,
                    "requires_approval": job["requires_approval"],
                    "approval_reason": "",
                    "approval_status": "not_required",
                    "final_answer": "",
                }
            else:
                # Retoma el checkpoint usando el mismo thread_id.
                graph_input = Command(
                    resume={"approved": approved}
                )

            # Un límite de tiempo evita trabajos RUNNING indefinidos.
            result = await asyncio.wait_for(
                self.graph.ainvoke(graph_input, config=config),
                timeout=600,
            )

            interruptions = result.get("__interrupt__", ())

            if interruptions:
                job["status"] = "WAITING_APPROVAL"
                job["approval_details"] = interruptions[0].value

            elif result.get("approval_status") == "rejected":
                job["status"] = "REJECTED"
                job["final_answer"] = result.get("final_answer", "")
                job["approval_details"] = None

            elif result.get("task_completed"):
                job["status"] = "DONE"
                job["final_answer"] = result.get("final_answer", "")
                job["approval_details"] = None

            else:
                raise RuntimeError(
                    "El grafo terminó sin completar la tarea."
                )

        except asyncio.CancelledError:
            job["status"] = "FAILED"
            job["error"] = "La ejecución fue cancelada."
            raise

        except Exception as error:
            logger.exception("Falló el trabajo %s", job_id)
            job["status"] = "FAILED"

            # No guardamos mensajes del proveedor que puedan
            # contener información sensible.
            job["error"] = (
                "La ejecución falló. Tipo de error: "
                f"{type(error).__name__}. "
                "Revisá la terminal del servidor."
            )

        finally:
            job["execution_seconds"] = round(
                previous_seconds + perf_counter() - started,
                3,
            )
            await self.save_job(job)