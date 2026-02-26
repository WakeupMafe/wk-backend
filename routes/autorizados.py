from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from postgrest.exceptions import APIError
from utils.supabase_client import get_supabase
import time

router = APIRouter(prefix="/autorizados", tags=["Autorizados"])

# ✅ CACHE SIMPLE EN MEMORIA (pin -> (expira, data))
CACHE = {}  # { pin: (expires_epoch_seconds, data_dict) }
CACHE_TTL = 30  # segundos


class IncrementoReq(BaseModel):
    cedula: str
    incremento: int = 1


@router.post("/incrementar-encuesta")
def incrementar_encuesta(req: IncrementoReq):
    supabase = get_supabase()

    try:
        # 1️⃣ Buscar autorizado por cédula
        q = (
            supabase.table("autorizados")
            .select("encuestas_realizadas")
            .eq("cedula", req.cedula)
            .limit(1)
            .execute()
        )

        if not q.data:
            raise HTTPException(
                status_code=404,
                detail=f"No existe autorizado con cédula {req.cedula}",
            )

        actual = q.data[0].get("encuestas_realizadas") or 0
        nuevo = actual + (req.incremento or 1)

        # 2️⃣ Actualizar directamente por cedula (porque es PK)
        upd = (
            supabase.table("autorizados")
            .update({"encuestas_realizadas": nuevo})
            .eq("cedula", req.cedula)
            .execute()
        )

        # ✅ OPCIONAL: invalidar cache de ese usuario si guardas pin en cache.
        # (No sabemos el pin aquí, así que lo dejamos. Si luego mandas pin,
        # podemos limpiar CACHE[pin] cuando incrementas)

        return {
            "ok": True,
            "cedula": req.cedula,
            "antes": actual,
            "despues": nuevo,
            "data": upd.data,
        }

    except APIError as e:
        raise HTTPException(
            status_code=400,
            detail={"where": "SUPABASE UPDATE", "error": str(e)},
        )


@router.get("/pin/{pin}")
def get_autorizado_por_pin(pin: str, request: Request):
    # ✅ 1) Revisar cache primero (ahorra el viaje a Supabase)
    now = time.time()
    cached = CACHE.get(pin)

    if cached:
        expira, data = cached
        if now < expira:
            print(f"⚡ cache hit pin: {pin}")
            return {"ok": True, "data": data}
        else:
            # expiró
            CACHE.pop(pin, None)

    # ✅ 2) Si no hay cache, consultar a Supabase 
    supabase = get_supabase()
    t0 = time.perf_counter()

    try:
        res = (
            supabase.table("autorizados")
           .select("cedula,nombres,apellidos,sede,encuestas_realizadas")
            .eq("pin", pin)
            .limit(1)
            .execute()
        )

        t1 = time.perf_counter()
        print(f"⏱️ /autorizados/pin/* supabase.execute(): {(t1 - t0)*1000:.0f} ms")

        if not res.data:
            raise HTTPException(status_code=404, detail="PIN no encontrado.")

        data = res.data[0]

        # ✅ 3) Guardar en cache por 30s
        CACHE[pin] = (now + CACHE_TTL, data)

        return {"ok": True, "data": data}

    except APIError as e:
        raise HTTPException(
            status_code=400,
            detail={"where": "SUPABASE SELECT", "error": str(e)},
        )