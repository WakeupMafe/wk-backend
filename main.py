import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes.verificacion import router as verificacion_router
from routes.encuestas import router as encuestas_router
from routes.autorizados import router as autorizados_router

BASE_DIR = Path(__file__).resolve().parent

# ✅ Solo cargar .env en local (Render ya usa Environment Variables)
if not os.getenv("RENDER"):
    load_dotenv(BASE_DIR / ".env")

app = FastAPI(debug=True)

# ✅ CORS completo (localhost y 127 + Netlify)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5176",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "https://wkseguimientos.netlify.app",
        "https://www.wkseguimientos.netlify.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Rutas
app.include_router(verificacion_router)
app.include_router(encuestas_router)
app.include_router(autorizados_router)

@app.get("/")
def root():
    return {"okii": True}