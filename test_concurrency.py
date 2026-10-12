import asyncio
import time

import httpx

BASE_URL = "http://127.0.0.1:8000"

QUERIES = [
    "Analizá las ventas de llaveros.",
    "Analizá las ventas de miniaturas.",
    "Analizá las ventas de dummys.",
    "Calculá la facturación total de todos los productos.",
    "Compará las ventas de llaveros y miniaturas.",
]


async def submit(client, number, query):
    start = time.perf_counter()
    response = await client.post(
        f"{BASE_URL}/tasks",
        json={"user_query": query, "requires_approval": False},
    )
    response.raise_for_status()
    job_id = response.json()["job_id"]
    elapsed = time.perf_counter() - start
    print(f"Solicitud {number}: HTTP {response.status_code} "
          f"en {elapsed:.3f}s | {job_id}", flush=True)
    return number, job_id


async def wait_result(client, number, job_id):
    deadline = time.perf_counter() + 660
    while time.perf_counter() < deadline:
        response = await client.get(f"{BASE_URL}/tasks/{job_id}")
        response.raise_for_status()
        data = response.json()
        if data["status"] in {"DONE", "FAILED", "REJECTED"}:
            print(
                f"Resultado {number}: {data['status']} | "
                f"{data['execution_seconds']}s | "
                f"Error: {data.get('error')}",
                flush=True,
            )
            return data
        await asyncio.sleep(2)
    raise TimeoutError(f"La solicitud {number} no terminó a tiempo.")


async def main():
    async with httpx.AsyncClient(timeout=30) as client:
        jobs = await asyncio.gather(*[
            submit(client, number, query)
            for number, query in enumerate(QUERIES, start=1)
        ])
        print("\nLas cinco solicitudes fueron aceptadas.\n", flush=True)
        results = await asyncio.gather(*[
            wait_result(client, number, job_id)
            for number, job_id in jobs
        ])
        completed = sum(item["status"] == "DONE" for item in results)
        print(f"\nTareas completadas correctamente: {completed}/5")


if __name__ == "__main__":
    asyncio.run(main())