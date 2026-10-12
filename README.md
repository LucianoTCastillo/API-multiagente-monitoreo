# Entregable 7 — API multiagente y monitoreo

API asíncrona para analizar ventas ficticias mediante un sistema
multiagente con LangGraph y un modelo de Groq.

Incluye persistencia de tareas y checkpoints en Redis, aprobación
humana y monitoreo de ejecuciones en LangSmith.

## Tecnologías

- Python 3.12
- FastAPI y Uvicorn
- LangGraph
- LangChain y Groq
- Redis 8
- LangSmith
- Docker Compose
- HTTPX

## Funcionamiento

La API recibe una consulta y devuelve HTTP 202 con un `job_id`,
sin esperar a que termine el análisis.

Cinco workers asíncronos procesan las tareas. El grafo contiene:

- Evaluación inicial: determina si se necesita aprobación humana.
- Aprobación humana: pausa el grafo hasta recibir una decisión.
- Supervisor: decide qué agente debe intervenir y valida los resultados.
- Investigador: consulta ventas ficticias mediante una herramienta SQLite.
- Analista: calcula unidades y facturación mediante una herramienta Python.

Redis almacena el estado de las tareas y los checkpoints del grafo.
Cada tarea utiliza su `job_id` como `thread_id`.

## Datos de demostración

| Producto | Unidades | Precio unitario ARS | Facturación ARS |
|---|---:|---:|---:|
| Llaveros | 50 | 1.300 | 65.000 |
| Miniaturas | 12 | 4.500 | 54.000 |
| Dummys | 8 | 6.500 | 52.000 |
| Total | 70 | — | 171.000 |

Los datos son ficticios. La facturación no representa ganancias,
porque no se consideran costos.

## Requisitos

- Python 3.12.
- Docker Desktop iniciado, para ejecutar Redis con Compose.
- Una API key de Groq y acceso al modelo configurado.
- Una API key de LangSmith para registrar trazas.

## Instalación

Crear y activar un entorno virtual en Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Instalar las dependencias:

```powershell
python -m pip install -r requirements.txt
```

Copiar la configuración de ejemplo:

```powershell
Copy-Item .env.example .env
```

Editar `.env` y colocar las claves reales de Groq y LangSmith.

El modelo utilizado en las pruebas fue `qwen/qwen3.8-27b`.
La disponibilidad y los límites dependen de la cuenta del proveedor.

No publicar `.env` ni las claves reales en el repositorio.

## Iniciar Redis

Desde la raíz del proyecto:

```powershell
docker compose up -d redis
```

Comprobar la conexión:

```powershell
docker compose exec redis redis-cli ping
```

La respuesta esperada es `PONG`.

Redis utiliza un volumen persistente y AOF.
El puerto se publica únicamente en `127.0.0.1`.

## Iniciar la API

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Documentación interactiva:

http://127.0.0.1:8000/docs

Ejecutar un solo proceso de Uvicorn, ya que la cola de trabajo
pertenece a la memoria de ese proceso.

## Endpoints

| Método | Ruta | Función |
|---|---|---|
| GET | `/health` | Comprueba la conexión con Redis |
| POST | `/tasks` | Crea y encola una tarea |
| GET | `/tasks/{job_id}` | Consulta el estado y el resultado |
| POST | `/tasks/{job_id}/approve` | Aprueba o rechaza una tarea pausada |

## Prueba de una tarea

Desde Swagger, ejecutar POST `/tasks` con:

```json
{
  "user_query": "Analizá las ventas de todos los productos.",
  "requires_approval": false
}
```

Copiar el `job_id` recibido y utilizarlo en GET `/tasks/{job_id}`.

Repetir el GET hasta obtener un estado final.

Estados posibles:

- `PENDING`: tarea encolada.
- `RUNNING`: tarea en ejecución.
- `WAITING_APPROVAL`: espera una decisión humana.
- `DONE`: análisis terminado.
- `REJECTED`: tarea rechazada por una persona.
- `FAILED`: ejecución fallida.

La respuesta final aparece en `final_answer`.
Si falla, `error` informa el tipo de error; el detalle se registra
en la terminal del servidor.

## Aprobación humana

Crear una tarea con:

```json
{
  "user_query": "Analizá las ventas de llaveros.",
  "requires_approval": true
}
```

Consultar su estado hasta obtener `WAITING_APPROVAL`.

Ejecutar POST `/tasks/{job_id}/approve`, usando el mismo identificador:

```json
{
  "approved": true
}
```

Volver a consultar GET `/tasks/{job_id}` hasta que termine.

Para rechazar una tarea que está esperando aprobación:

```json
{
  "approved": false
}
```

El grafo también solicita aprobación cuando detecta determinadas
expresiones críticas, como eliminar, enviar o modificar precios.

Esta detección por frases es una demostración básica.
El proyecto no ejecuta acciones externas ni modifica las ventas.

## Prueba de cinco solicitudes concurrentes

Con Redis y la API funcionando, abrir otra terminal y ejecutar:

```powershell
python test_concurrency.py
```

El script envía cinco solicitudes mediante `asyncio.gather`,
muestra sus identificadores y consulta los resultados.

Resultado observado en la prueba final: **5/5 tareas en DONE**.

| Solicitud | Consulta | Tiempo de ejecución |
|---|---|---:|
| 1 | Ventas de llaveros | 153,347 s |
| 2 | Ventas de miniaturas | 340,238 s |
| 3 | Ventas de dummys | 189,472 s |
| 4 | Facturación total | 214,106 s |
| 5 | Comparación de llaveros y miniaturas | 263,843 s |

Los tiempos incluyen las esperas y los reintentos por límites
del proveedor. No son los tiempos de respuesta del POST inicial.

## Manejo de límites de Groq

Durante las pruebas se alcanzó un límite de 1.000 tokens de salida
por minuto, lo que produjo respuestas HTTP 429.

Se configuró el cliente con:

- `max_tokens=512`
- `max_retries=20`

Los reintentos permiten esperar ante errores temporales;
no aumentan la cuota del proveedor.

La ejecución de cada tarea tiene un timeout de 600 segundos.
Una tarea puede fallar si agota los reintentos o supera ese tiempo.

## Monitoreo con LangSmith

La configuración utiliza:

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=colocar_clave_langsmith
LANGSMITH_PROJECT=entregable7-api-monitoreo
```

LangSmith registra las ejecuciones del grafo, agentes,
herramientas y llamadas al modelo.

Las trazas permiten consultar latencia, tokens y costos estimados.

El dashboard personalizado contiene:

- Costo promedio por ejecución: Cost, agregación Average.
- Latencia P95: Latency, agregación Percentile 95.
- Filtro de trazas raíz: Is Trace is true.
- Visualización KPI para mostrar ambos valores numéricos.

En la captura final, el dashboard mostró:

| Métrica | Valor mostrado |
|---|---:|
| Costo promedio estimado por traza | USD 0,01 |
| Latencia P95 | 263,8 s |

Estos valores corresponden al período seleccionado e incluyen
pruebas previas, errores y ejecuciones de pausa/reanudación.
No representan exclusivamente las cinco tareas de la prueba final.

El costo mostrado es una estimación basada en tokens y tarifas
registradas por LangSmith; no es un comprobante de cobro.

## Evidencias

La carpeta `screenshots` contiene capturas de:

- Tarea en espera de aprobación humana.
- Tarea completada después de aprobarla.
- Cinco solicitudes concurrentes terminadas correctamente.
- Trazas con tokens, costos y latencias.
- Dashboard de costo promedio y latencia P95.

## Limitaciones

- La cola de trabajo está en memoria; no es una cola persistente en Redis.
- Redis persiste los registros de tareas y los checkpoints del grafo.
- Un cierre abrupto puede dejar tareas pendientes o en ejecución
  sin recuperación automática.
- Los tiempos dependen de los límites y la disponibilidad de Groq.
- La prueba de cinco solicitudes es una demostración funcional,
  no una evaluación de rendimiento con una muestra grande.
- La API está diseñada para una demostración local y no incluye
  autenticación de usuarios.
- Las ventas se generan en SQLite en memoria y son ficticias.

## Detener los servicios

Detener Uvicorn con Ctrl+C.

Detener Redis conservando el volumen:

```powershell
docker compose down
```