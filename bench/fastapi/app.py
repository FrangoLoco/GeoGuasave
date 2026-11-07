"""Prototipo FastAPI de GET /reverse para la prueba preliminar de backend (Fase 4, tarea 1)."""
import os
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, Response

POOL = int(os.environ.get("POOL", "10"))


@asynccontextmanager
async def lifespan(app):
    app.state.pool = await asyncpg.create_pool(
        host="db", user=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"],
        database=os.environ["POSTGRES_DB"], min_size=POOL, max_size=POOL)
    yield
    await app.state.pool.close()


app = FastAPI(lifespan=lifespan)


@app.get("/reverse")
async def reverse(lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180)):
    r = await app.state.pool.fetchval("SELECT geo.reverse_geocode($1, $2)::text", lon, lat)
    if r is None:
        return JSONResponse({"detalle": "punto fuera de Sinaloa"}, status_code=422)
    return Response(r, media_type="application/json")
