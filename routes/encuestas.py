from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field, root_validator
from typing import List, Optional, Dict
from postgrest.exceptions import APIError
from collections import Counter
from datetime import datetime, timedelta, timezone
import logging
import re

from utils.supabase_client import get_supabase

router = APIRouter(prefix="/encuestas", tags=["Encuestas"])

logger = logging.getLogger(__name__)

# ------- Helpers --------

def limpiar_documento_encuestador(doc: str) -> str:
    """Cédula del encuestador: solo dígitos, 6 a 11."""
    doc = (doc or "").strip()

    if not re.fullmatch(r"\d+", doc):
        raise HTTPException(status_code=400, detail="El documento debe contener solo números.")

    if len(doc) < 6 or len(doc) > 11:
        raise HTTPException(status_code=400, detail="El documento debe tener entre 6 y 11 dígitos.")

    return doc


def limpiar_documento_paciente(doc: str, tipo_documento: Optional[str] = None) -> str:
    """
    Documento del paciente según tipo:
    - registro_civil, pasaporte: alfanumérico y guion, 5–30 caracteres
    - cédula, tarjeta de identidad, CE: solo dígitos, 6–11
    """
    t = (tipo_documento or "").strip().lower()
    doc = (doc or "").strip()

    if t in ("registro_civil", "pasaporte"):
        cleaned = re.sub(r"[^A-Za-z0-9\-]", "", doc)
        if len(cleaned) < 5 or len(cleaned) > 30:
            raise HTTPException(
                status_code=400,
                detail="Para registro civil o pasaporte use entre 5 y 30 caracteres (letras, números o guion).",
            )
        return cleaned.upper()

    if not re.fullmatch(r"\d+", doc):
        raise HTTPException(status_code=400, detail="El documento debe contener solo números.")

    if len(doc) < 6 or len(doc) > 11:
        raise HTTPException(status_code=400, detail="El documento debe tener entre 6 y 11 dígitos.")

    return doc


def limpiar_documento(doc: str) -> str:
    """Compatibilidad: mismo criterio que encuestador (solo dígitos 6–11)."""
    return limpiar_documento_encuestador(doc)


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
    doc_paciente = limpiar_documento_paciente(data.documento, data.tipoDocumento)
    doc_encuestador = limpiar_documento_encuestador(data.encuestador)

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
def encuesta_existe(
    documento: str,
    tipo_documento: Optional[str] = Query(None, description="Mismo tipo que en el formulario (ej. registro_civil)"),
):
    doc_paciente = limpiar_documento_paciente(documento, tipo_documento or "cedula")
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


def _count_exact(builder):
    res = builder.execute()
    n = getattr(res, "count", None)
    return int(n) if n is not None else 0


def _ranking_autorizados_desde_tabla(supabase, limit: int = 50) -> List[Dict]:
    """
    Ranking desde tabla `autorizados`: columnas pedidas, orden por encuestas_realizadas desc.
    Excluye filas con encuestas_realizadas nulo (tras la consulta).
    """
    cols = "cedula,nombres,apellidos,sede,encuestas_realizadas"
    try:
        res = (
            supabase.table("autorizados")
            .select(cols)
            .order("encuestas_realizadas", desc=True)
            .limit(limit)
            .execute()
        )
        rows = list(res.data or [])
    except APIError as e:
        logging.warning("ranking_autorizados: error Supabase al leer autorizados: %s", e)
        return []

    out: List[Dict] = []
    for r in rows:
        raw_n = r.get("encuestas_realizadas")
        if raw_n is None:
            continue
        try:
            n = int(raw_n)
        except (TypeError, ValueError):
            continue
        out.append(
            {
                "cedula": r.get("cedula"),
                "nombres": (r.get("nombres") or "").strip(),
                "apellidos": (r.get("apellidos") or "").strip(),
                "sede": (r.get("sede") or "").strip(),
                "encuestas_realizadas": n,
            }
        )
    return out


def _por_sede_encuestas(supabase) -> List[Dict]:
    """
    Recuenta encuestas (wakeup_seguimientos) por sede; pagina por si hay >1000 filas.
    """
    counter: Counter = Counter()
    offset = 0
    page = 1000
    while True:
        res = (
            supabase.table("wakeup_seguimientos")
            .select("sede")
            .range(offset, offset + page - 1)
            .execute()
        )
        rows = res.data or []
        for row in rows:
            s = (row.get("sede") or "").strip()
            key = s if s else "Sin sede"
            counter[key] += 1
        if len(rows) < page:
            break
        offset += page
    return [
        {"sede": k, "count": v}
        for k, v in sorted(counter.items(), key=lambda x: (-x[1], x[0]))
    ]


@router.get("/estadisticas-generales")
def estadisticas_generales(response: Response):
    """
    Agregados sobre wakeup_seguimientos para el panel de estadísticas.
    `ranking_autorizados`: filas de tabla `autorizados` ordenadas por encuestas_realizadas desc.
    """
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-WK-Ranking-Autorizados"] = "1"
    supabase = get_supabase()
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=30)).isoformat()

    try:
        total = _count_exact(
            supabase.table("wakeup_seguimientos").select("id_int", count="exact"),
        )

        # Al menos un síntoma = dolor
        con_dolor = _count_exact(
            supabase.table("wakeup_seguimientos")
            .select("id_int", count="exact")
            .or_("sintoma_1.eq.dolor,sintoma_2.eq.dolor,sintoma_3.eq.dolor"),
        )

        # Trastorno para dormir (valor del catálogo: dormir)
        con_trastorno_dormir = _count_exact(
            supabase.table("wakeup_seguimientos")
            .select("id_int", count="exact")
            .or_("sintoma_1.eq.dormir,sintoma_2.eq.dormir,sintoma_3.eq.dormir"),
        )

        con_tres_objetivos = _count_exact(
            supabase.table("wakeup_seguimientos")
            .select("id_int", count="exact")
            .eq("objetivos_seleccionados", 3),
        )

        con_dos_objetivos = _count_exact(
            supabase.table("wakeup_seguimientos")
            .select("id_int", count="exact")
            .eq("objetivos_seleccionados", 2),
        )

        ultimo_mes = _count_exact(
            supabase.table("wakeup_seguimientos")
            .select("id_int", count="exact")
            .gte("created_at", since),
        )

        por_sede = _por_sede_encuestas(supabase)

        ranking_autorizados: List[Dict] = []
        try:
            ranking_autorizados = _ranking_autorizados_desde_tabla(
                supabase, limit=50
            )
        except Exception as ex:
            logger.warning(
                "estadisticas-generales: ranking_autorizados vacío por excepción: %s",
                ex,
            )

        body = {
            "ok": True,
            "total": total,
            "con_dolor": con_dolor,
            "con_trastorno_dormir": con_trastorno_dormir,
            "con_tres_objetivos": con_tres_objetivos,
            "con_dos_objetivos": con_dos_objetivos,
            "ultimo_mes": ultimo_mes,
            "por_sede": por_sede,
            "actualizado_en": now.isoformat(),
        }
        body["ranking_autorizados"] = ranking_autorizados
        logger.info(
            "estadisticas-generales OK: claves=%s ranking_autorizados=%s filas",
            list(body.keys()),
            len(ranking_autorizados),
        )
        return body

    except APIError as e:
        raise HTTPException(
            status_code=400,
            detail={"where": "estadisticas-generales", "error": str(e)},
        )


# Valores de síntoma alineados con el catálogo del frontend (PROBLEMAS)
SINTOMAS_VALIDOS = frozenset(
    {
        "dolor",
        "intolerancia_postura",
        "limitacion_deporte",
        "trastorno_trabajo",
        "vida_social",
        "recrearse",
        "dormir",
        "escaleras",
        "levantarse_silla_cama",
        "autocuidado",
        "caminar_vehiculo",
        "recoger_objetos",
        "cargar_paquetes",
        "conducir",
        "otro",
    }
)


def _sintomas_en_fila(row: Dict) -> set:
    return {
        row.get("sintoma_1"),
        row.get("sintoma_2"),
        row.get("sintoma_3"),
    } - {None, ""}


def _fila_coincide_sintomas(row: Dict, sintomas: List[str]) -> bool:
    """True si la fila incluye al menos uno de los síntomas seleccionados (OR)."""
    if not sintomas:
        return True
    en_fila = _sintomas_en_fila(row)
    return bool(en_fila.intersection(sintomas))


TIPOS_DOC_VALIDOS = frozenset(
    {
        "pasaporte",
        "cedula",
        "tarjeta_identidad",
        "cedula_extranjeria",
        "registro_civil",
    }
)


def _safe_ilike_fragment(s: Optional[str]) -> Optional[str]:
    """Fragmento para ilike: sin comodines controlados por el usuario."""
    if not s:
        return None
    t = s.strip()[:200]
    if not t:
        return None
    return t.replace("%", "").replace("_", "")


@router.get("/listado-filtrado")
def listado_filtrado(
    sede: Optional[str] = Query(None, description="Filtrar por sede (vacío = todas)"),
    nombres: Optional[str] = Query(
        None,
        description="Texto contenido en nombres (sin distinguir mayúsculas)",
    ),
    apellidos: Optional[str] = Query(
        None,
        description="Texto contenido en apellidos (sin distinguir mayúsculas)",
    ),
    tipo_documento: Optional[str] = Query(
        None,
        description="Valor exacto del catálogo (ej. cedula); vacío = cualquiera",
    ),
    sintomas: Optional[str] = Query(
        None,
        description="Valores separados por coma, máximo 3 (ej: dolor,dormir)",
    ),
    limit: int = Query(800, ge=1, le=2000),
):
    """
    Listado de encuestas para la pantalla Filtros: sede, texto en nombres/apellidos,
    tipo de documento, y hasta 3 síntomas (OR: al menos uno en la fila).
    """
    supabase = get_supabase()
    raw_sintomas: List[str] = []
    if sintomas and sintomas.strip():
        parts = [p.strip() for p in sintomas.split(",") if p.strip()]
        raw_sintomas = parts[:3]
        for s in raw_sintomas:
            if s not in SINTOMAS_VALIDOS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Síntoma no válido: {s}",
                )

    sede_clean = (sede or "").strip() or None

    nombres_frag = _safe_ilike_fragment(nombres)
    apellidos_frag = _safe_ilike_fragment(apellidos)

    tipo_clean = (tipo_documento or "").strip() or None
    if tipo_clean and tipo_clean not in TIPOS_DOC_VALIDOS:
        raise HTTPException(
            status_code=400,
            detail=f"tipo_documento no válido: {tipo_clean}",
        )

    try:
        q = (
            supabase.table("wakeup_seguimientos")
            .select(
                "id_int,documento,nombres,apellidos,tipo_documento,sede,sintoma_1,sintoma_2,sintoma_3,"
                "created_at,objetivos_seleccionados"
            )
            .order("created_at", desc=True)
            .limit(limit)
        )
        if sede_clean:
            q = q.eq("sede", sede_clean)
        if nombres_frag:
            q = q.ilike("nombres", f"%{nombres_frag}%")
        if apellidos_frag:
            q = q.ilike("apellidos", f"%{apellidos_frag}%")
        if tipo_clean:
            q = q.eq("tipo_documento", tipo_clean)

        res = q.execute()
        rows = res.data or []

        if raw_sintomas:
            rows = [r for r in rows if _fila_coincide_sintomas(r, raw_sintomas)]

        total_base = _count_exact(
            supabase.table("wakeup_seguimientos").select("id_int", count="exact"),
        )

        return {
            "ok": True,
            "rows": rows,
            "mostrados": len(rows),
            "total_en_base": total_base,
            "filtros": {
                "sede": sede_clean,
                "nombres": nombres_frag,
                "apellidos": apellidos_frag,
                "tipo_documento": tipo_clean,
                "sintomas": raw_sintomas,
            },
            "actualizado_en": datetime.now(timezone.utc).isoformat(),
        }

    except APIError as e:
        raise HTTPException(
            status_code=400,
            detail={"where": "listado-filtrado", "error": str(e)},
        )