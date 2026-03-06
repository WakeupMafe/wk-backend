from pydantic import BaseModel, EmailStr
from fastapi import APIRouter, HTTPException, BackgroundTasks
from supabase import create_client
from postgrest.exceptions import APIError
from utils.pin_utils import generar_pin_2letras_3numeros
from utils.email_utils import enviar_pin_por_correo
import os
import re

router = APIRouter(prefix="/verificacion", tags=["verificacion"])


# =========================
# HELPERS
# =========================
def only_digits(s: str) -> str:
    return re.sub(r"\D+", "", (s or "")).strip()


def clean_str(s: str) -> str:
    return (s or "").strip()


def to_int_or_400(value: str, field_name="Cédula") -> int:
    try:
        return int(value)
    except Exception:
        raise HTTPException(status_code=400, detail=f"{field_name} inválida")


# =========================
# MODELOS
# =========================
class RegistroInicialIn(BaseModel):
    nombres: str
    apellidos: str
    correo: EmailStr
    celular: str
    sede: str
    cedula: str


class CedulaIn(BaseModel):
    cedula: str


class PinIn(BaseModel):
    cedula: str
    pin: str


class ReenviarPinIn(BaseModel):
    cedula: str


# =========================
# SUPABASE
# =========================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY en .env")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# =========================
# ENDPOINTS
# =========================
@router.get("/pin-test")
def pin_test():
    return {"pin": generar_pin_2letras_3numeros()}


@router.post("/registro-inicial")
def registro_inicial(data: RegistroInicialIn, background_tasks: BackgroundTasks):
    payload = data.model_dump()

    cedula_str = only_digits(payload.get("cedula"))
    celular = only_digits(payload.get("celular"))
    correo = clean_str(payload.get("correo")).lower()
    sede = clean_str(payload.get("sede"))
    nombres = clean_str(payload.get("nombres"))
    apellidos = clean_str(payload.get("apellidos"))

    if not cedula_str:
        raise HTTPException(status_code=400, detail="Cédula inválida")
    if not sede:
        raise HTTPException(status_code=400, detail="Sede obligatoria")

    cedula = to_int_or_400(cedula_str, "Cédula")

    try:
        existente = (
            supabase
            .table("autorizados")
            .select("cedula, correo, pin")
            .eq("cedula", cedula)
            .limit(1)
            .execute()
        )
    except APIError as e:
        raise HTTPException(
            status_code=400,
            detail={"where": "SUPABASE SELECT EXISTENTE", "error": str(e)},
        )

    if existente.data:
        raise HTTPException(
            status_code=409,
            detail="El usuario que intentas registrar ya está en nuestro sistema.",
        )

    pin = generar_pin_2letras_3numeros()

    try:
        resp = (
            supabase
            .table("autorizados")
            .insert(
                {
                    "cedula": cedula,
                    "pin": pin,
                    "nombres": nombres,
                    "apellidos": apellidos,
                    "correo": correo,
                    "celular": celular,
                    "sede": sede,
                }
            )
            .execute()
        )
    except APIError as e:
        raise HTTPException(
            status_code=400,
            detail={"where": "SUPABASE INSERT", "error": str(e)},
        )

    if not resp.data:
        raise HTTPException(status_code=500, detail="No se pudo guardar en autorizados")

    background_tasks.add_task(enviar_pin_por_correo, correo, pin)

    return {
        "ok": True,
        "message": "Usuario registrado correctamente. PIN enviado al correo.",
    }


@router.post("/cedula")
def verificar_cedula(payload: CedulaIn):
    cedula_str = only_digits(payload.cedula)
    if not cedula_str:
        raise HTTPException(status_code=400, detail="Cédula inválida")

    cedula = to_int_or_400(cedula_str, "Cédula")

    try:
        resp = (
            supabase
            .table("autorizados")
            .select("cedula, nombres, correo")
            .eq("cedula", cedula)
            .limit(1)
            .execute()
        )
    except APIError as e:
        raise HTTPException(
            status_code=400,
            detail={"where": "SUPABASE SELECT", "error": str(e)},
        )

    return {
        "ok": bool(resp.data),
        "exists": bool(resp.data),
        "message": "Cédula encontrada" if resp.data else "Cédula no encontrada",
    }


@router.post("/pin")
def verificar_pin(payload: PinIn):
    cedula_str = only_digits(payload.cedula)
    pin = clean_str(payload.pin)

    if not cedula_str:
        raise HTTPException(status_code=400, detail="Cédula inválida")
    if not pin:
        raise HTTPException(status_code=400, detail="PIN vacío")

    cedula = to_int_or_400(cedula_str, "Cédula")

    try:
        resp = (
            supabase
            .table("autorizados")
            .select("pin, nombres, sede")
            .eq("cedula", cedula)
            .limit(1)
            .execute()
        )
    except APIError as e:
        raise HTTPException(
            status_code=400,
            detail={"where": "SUPABASE SELECT", "error": str(e)},
        )

    if not resp.data:
        return {"ok": False}

    row = resp.data[0]
    pin_db = clean_str(row.get("pin"))

    if pin_db != pin:
        return {"ok": False}

    return {
        "ok": True,
        "usuario": row.get("nombres"),
        "sede": row.get("sede"),
    }


@router.post("/reenviar-pin")
def reenviar_pin(payload: ReenviarPinIn, background_tasks: BackgroundTasks):
    cedula_str = only_digits(payload.cedula)
    if not cedula_str:
        raise HTTPException(status_code=400, detail="Cédula inválida")

    cedula = to_int_or_400(cedula_str, "Cédula")

    try:
        resp = (
            supabase
            .table("autorizados")
            .select("correo, pin")
            .eq("cedula", cedula)
            .limit(1)
            .execute()
        )
    except APIError as e:
        raise HTTPException(
            status_code=400,
            detail={"where": "SUPABASE SELECT", "error": str(e)},
        )

    if not resp.data:
        raise HTTPException(status_code=404, detail="Cédula no encontrada")

    correo = clean_str(resp.data[0].get("correo")).lower()
    pin = clean_str(resp.data[0].get("pin"))

    if not correo:
        raise HTTPException(status_code=400, detail="No hay correo registrado")
    if not pin:
        raise HTTPException(status_code=400, detail="No hay PIN registrado para reenviar")

    background_tasks.add_task(enviar_pin_por_correo, correo, pin)

    return {
        "ok": True,
        "message": "PIN reenviado correctamente",
    }