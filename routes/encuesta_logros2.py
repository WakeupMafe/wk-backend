from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List
from postgrest.exceptions import APIError

from utils.supabase_client import get_supabase
from routes.encuestas import limpiar_documento_encuestador, limpiar_documento_paciente

router = APIRouter(prefix="/encuestas", tags=["Encuestas"])


class ItemLogros2(BaseModel):
    slot: int = Field(ge=1, le=3)
    sintoma: str
    nivel_mejora: str  # mucho | poco | nada
    nuevo_objetivo: str


class EncuestaLogros2In(BaseModel):
    encuestador: str
    sede: str
    documento: str
    id_encuesta_fase1: int
    items: List[ItemLogros2]


NIVELES = {"mucho", "poco", "nada"}


@router.post("/logros2")
def crear_encuesta_logros2(data: EncuestaLogros2In):
    doc_paciente = limpiar_documento_paciente(data.documento, "cedula")
    doc_encuestador = limpiar_documento_encuestador(data.encuestador)

    sede_clean = (data.sede or "").strip()
    if not sede_clean:
        raise HTTPException(status_code=400, detail="La sede es obligatoria.")

    if not data.items:
        raise HTTPException(status_code=400, detail="Debe enviar al menos un ítem de seguimiento.")

    for it in data.items:
        if it.nivel_mejora not in NIVELES:
            raise HTTPException(
                status_code=400,
                detail=f"Nivel de mejora inválido en síntoma {it.slot}: use mucho, poco o nada.",
            )
        if not (it.nuevo_objetivo or "").strip():
            raise HTTPException(status_code=400, detail=f"Indique el nuevo objetivo para el síntoma {it.slot}.")

    supabase = get_supabase()

    try:
        check = (
            supabase
            .table("wakeup_seguimientos")
            .select("id_int, documento")
            .eq("id_int", data.id_encuesta_fase1)
            .limit(1)
            .execute()
        )
    except APIError as e:
        raise HTTPException(status_code=400, detail={"where": "SUPABASE SELECT FASE1", "error": str(e)})

    if not check.data:
        raise HTTPException(status_code=404, detail="No se encontró la encuesta de logros (fase 1) indicada.")

    row_f1 = check.data[0]
    doc_f1 = row_f1.get("documento")
    if doc_f1 is not None and str(doc_f1).strip() != str(doc_paciente).strip():
        raise HTTPException(status_code=400, detail="El documento no coincide con la encuesta base.")

    respuestas = [it.model_dump() for it in data.items]

    insert_row = {
        "documento": int(doc_paciente) if doc_paciente.isdigit() else doc_paciente,
        "encuestador": int(doc_encuestador) if doc_encuestador.isdigit() else doc_encuestador,
        "sede": sede_clean,
        "id_encuesta_fase1": data.id_encuesta_fase1,
        "respuestas": respuestas,
    }

    try:
        res = supabase.table("wakeup_seguimientos_logros2").insert(insert_row).execute()
        return {"ok": True, "data": res.data}
    except APIError as e:
        raise HTTPException(status_code=400, detail={"where": "SUPABASE INSERT LOGROS2", "error": str(e), "row": insert_row})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error insertando seguimiento: {repr(e)}")
