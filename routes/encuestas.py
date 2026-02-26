from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, root_validator
from typing import List, Optional, Dict
from postgrest.exceptions import APIError
import re

from utils.supabase_client import get_supabase

router = APIRouter(prefix="/encuestas", tags=["Encuestas"])

# ------- Helpers --------

def limpiar_documento(doc: str) -> str:
    """
    Devuelve documento limpio como STRING:
    - solo dígitos
    - longitud 6 a 10
    """
    doc = (doc or "").strip()

    if not re.fullmatch(r"\d+", doc):
        raise HTTPException(status_code=400, detail="El documento debe contener solo números.")

    if len(doc) < 6 or len(doc) > 10:
        raise HTTPException(status_code=400, detail="El documento debe tener entre 6 y 10 dígitos.")

    return doc


def validar_min_max(lista: List[str], campo: str, min_v: int, max_v: int):
    if len(lista) < min_v:
        raise HTTPException(status_code=400, detail=f"{campo}: debe seleccionar mínimo {min_v}.")
    if len(lista) > max_v:
        raise HTTPException(status_code=400, detail=f"{campo}: máximo {max_v}.")


def a_columna_fija(items: List[Optional[str]], n: int = 3) -> Dict[str, Optional[str]]:
    out: Dict[str, Optional[str]] = {}
    for i in range(n):
        out[f"_{i+1}"] = items[i] if i < len(items) else None
    return out


# ------- Payload esperado desde el frontend --------

class EncuestaIn(BaseModel):
    encuestador: str   # cédula del encuestador (string)
    sede: str

    nombres: str
    apellidos: str
    tipoDocumento: str
    documento: str     # documento del paciente (string)

    limitacionMoverse: str
    actividadesAfectadas: List[str] = Field(default_factory=list)

    sintomasTop: List[str]  # 1..3
    otroSintoma: Optional[str] = None

    objetivos: Dict[str, str]  # min 1, max 3
    textos: Dict[str, str] = Field(default_factory=dict)

    detalles: Optional[Dict[str, str]] = None

    objetivoExtra: Optional[str] = None
    adicionalNoPuede: Optional[str] = None
    ultimaVez: Optional[str] = None
    queImpide: List[str] = Field(default_factory=list)

    @root_validator(pre=True)
    def map_detalles_to_textos(cls, values):
        if isinstance(values, dict):
            if "textos" not in values and "detalles" in values and isinstance(values["detalles"], dict):
                values["textos"] = values["detalles"]
        return values


@router.post("/")
def crear_encuesta(data: EncuestaIn):
    # ---- Limpieza/validación docs como STRING ----
    doc_paciente = limpiar_documento(data.documento)
    doc_encuestador = limpiar_documento(data.encuestador)

    sede_clean = (data.sede or "").strip()
    if not sede_clean:
        raise HTTPException(status_code=400, detail="La sede es obligatoria.")

    validar_min_max(data.sintomasTop, "Síntomas", 1, 3)

    objetivos_keys = list(data.objetivos.keys())
    validar_min_max(objetivos_keys, "Objetivos", 1, 3)

    sintomas_set = set(data.sintomasTop)
    for s in objetivos_keys:
        if s not in sintomas_set:
            raise HTTPException(
                status_code=400,
                detail=f"El objetivo para '{s}' no es válido porque ese síntoma no está en los 3 seleccionados."
            )

    if "otro" in sintomas_set and (not data.otroSintoma or not data.otroSintoma.strip()):
        raise HTTPException(status_code=400, detail="Debe especificar el síntoma 'Otro'.")

    supabase = get_supabase()

    # ✅ BLOQUEO DUPLICADOS (por documento del paciente)
    ya_existe = (
        supabase
        .table("wakeup_seguimientos")
        .select("id_int")
        .eq("documento", doc_paciente)  # string vs string
        .limit(1)
        .execute()
    )
    if ya_existe.data:
        raise HTTPException(
            status_code=409,
            detail="Este usuario ya tiene encuesta. No es posible realizar otra encuesta."
        )

    # ---- Construir columnas fijas ----
    sintomas_ordenados = data.sintomasTop[:3]
    objetivos_ordenados: List[Optional[str]] = []
    detalles_ordenados: List[Optional[str]] = []

    for s in sintomas_ordenados:
        if s in data.objetivos:
            objetivos_ordenados.append(data.objetivos[s])
            detalles_ordenados.append(data.textos.get(s))
        else:
            objetivos_ordenados.append(None)
            detalles_ordenados.append(data.textos.get(s))

    objetivos_reales = [o for o in objetivos_ordenados if o is not None]
    objetivos_seleccionados = len(objetivos_reales)
    if objetivos_seleccionados < 1:
        raise HTTPException(status_code=400, detail="Debe seleccionar mínimo 1 objetivo.")

    obj_cols = a_columna_fija(objetivos_reales, 3)
    sin_cols = a_columna_fija(sintomas_ordenados, 3)

    # ---- Registro para Supabase ----
    row = {
        "encuestador": doc_encuestador,  # STRING
        "sede": sede_clean,

        "nombres": data.nombres.strip(),
        "apellidos": data.apellidos.strip(),
        "tipo_documento": data.tipoDocumento,
        "documento": doc_paciente,       # STRING

        "limitacion_moverse": data.limitacionMoverse,
        "actividades_afectadas": data.actividadesAfectadas,

        "sintoma_1": sin_cols["_1"],
        "sintoma_2": sin_cols["_2"],
        "sintoma_3": sin_cols["_3"],

        "otro_sintoma": data.otroSintoma.strip() if data.otroSintoma else None,

        "objetivo_1": obj_cols["_1"],
        "objetivo_2": obj_cols["_2"],
        "objetivo_3": obj_cols["_3"],

        "objetivos_seleccionados": objetivos_seleccionados,

        "objetivo_extra": data.objetivoExtra,
        "adicional_no_puede": data.adicionalNoPuede,
        "ultima_vez": data.ultimaVez,
        "que_impide": data.queImpide,
    }

    try:
        res = supabase.table("wakeup_seguimientos").insert(row).execute()
        return {"ok": True, "data": res.data}

    except APIError as e:
        raise HTTPException(status_code=400, detail={"where": "SUPABASE INSERT", "error": str(e), "row": row})

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error insertando en Supabase: {repr(e)}")


@router.get("/exists/{documento}")
def encuesta_existe(documento: str):
    doc_paciente = limpiar_documento(documento)
    supabase = get_supabase()

    res = (
        supabase
        .table("wakeup_seguimientos")
        .select("id_int")
        .eq("documento", doc_paciente)  # string vs string
        .limit(1)
        .execute()
    )

    return {"ok": True, "exists": bool(res.data)}