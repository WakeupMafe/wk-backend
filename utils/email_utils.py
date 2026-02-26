# backend/utils/email_utils.py

import os
import smtplib
import time
from pathlib import Path
from dotenv import load_dotenv
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate

# ✅ Cargar .env (robusto): sube hasta /backend
BASE_DIR = Path(__file__).resolve().parents[1]  # .../backend
load_dotenv(BASE_DIR / ".env", override=True)

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")

# ✅ IMPORTANTÍSIMO: el FROM debe ser el MISMO usuario que autentica en Gmail
SMTP_FROM = "fernanda.grimaldo018@gmail.com"

# 🔎 DEBUG (esto sale en la consola del backend/uvicorn)
print("📧 SMTP_HOST LEIDO:", SMTP_HOST, flush=True)
print("📧 SMTP_PORT LEIDO:", SMTP_PORT, flush=True)
print("📧 SMTP_USER LEIDO:", SMTP_USER, flush=True)
print("📧 SMTP_FROM LEIDO:", SMTP_FROM, flush=True)


def _validar_env_smtp():
    faltan = []
    if not SMTP_HOST:
        faltan.append("SMTP_HOST")
    if not SMTP_PORT:
        faltan.append("SMTP_PORT")
    if not SMTP_USER:
        faltan.append("SMTP_USER")
    if not SMTP_PASS:
        faltan.append("SMTP_PASS")
    if not SMTP_FROM:
        faltan.append("SMTP_FROM/SMTP_USER")

    if faltan:
        raise RuntimeError(f"❌ Faltan variables SMTP en .env: {', '.join(faltan)}")


def enviar_pin_por_correo(destinatario: str, pin: str):
    t0 = time.perf_counter()
    print(f"🚀 enviar_pin_por_correo() llamado -> {destinatario}", flush=True)

    _validar_env_smtp()

    destinatario = (destinatario or "").strip()
    pin = (pin or "").strip()

    if not destinatario:
        raise ValueError("❌ Destinatario vacío")
    if not pin:
        raise ValueError("❌ PIN vacío")

    msg = MIMEMultipart()
    msg["From"] = SMTP_FROM
    msg["To"] = destinatario
    msg["Subject"] = "Tu código de acceso"
    msg["Reply-To"] = SMTP_FROM
    msg["Date"] = formatdate(localtime=True)

    body = f"""Hola,

Tu código de acceso es:

    {pin}

Este código es personal y no debe compartirse.
Por favor guarda el código de acceso para futuras visitas.

Si no solicitaste este acceso, ignora este mensaje.
"""
    msg.attach(MIMEText(body, "plain"))

    try:
        t1 = time.perf_counter()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            print(f"⏱️ conectó SMTP en {(time.perf_counter() - t1) * 1000:.0f} ms", flush=True)

            # 🔥 Si algún día necesitas ver el detalle SMTP, activa esto:
            # server.set_debuglevel(1)

            t2 = time.perf_counter()
            server.ehlo()
            server.starttls()
            server.ehlo()
            print(f"⏱️ TLS+EHLO en {(time.perf_counter() - t2) * 1000:.0f} ms", flush=True)

            t3 = time.perf_counter()
            server.login(SMTP_USER, SMTP_PASS)
            print(f"⏱️ login en {(time.perf_counter() - t3) * 1000:.0f} ms", flush=True)

            t4 = time.perf_counter()
            result = server.sendmail(
                SMTP_FROM,
                [destinatario],
                msg.as_string(),
            )
            print(f"⏱️ sendmail en {(time.perf_counter() - t4) * 1000:.0f} ms", flush=True)

        print("📨 Resultado sendmail:", result, flush=True)
        print(f"⏱️ TOTAL enviar_pin_por_correo {(time.perf_counter() - t0):.2f} s", flush=True)

        if result == {}:
            print("✅ Gmail aceptó el correo para envío.", flush=True)
            return True, None

        # si hubo rechazo de destinatario
        print("⚠️ Algunos destinatarios fueron rechazados:", result, flush=True)
        return False, str(result)

    except Exception as e:
        print(f"⏱️ TOTAL (con error) {(time.perf_counter() - t0):.2f} s", flush=True)
        print("❌ ERROR ENVIANDO CORREO:", repr(e), flush=True)
        return False, repr(e)