from pathlib import Path
from dotenv import load_dotenv

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes.verificacion import router as verificacion_router
from routes.encuestas import router as encuestas_router
from routes.autorizados import router as autorizados_router

# ✅ Cargar .env con ruta absoluta (evita fallos con uvicorn --reload)
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=True)

app = FastAPI(debug=True)

# ✅ CORS completo (localhost y 127 + Netlify)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "https://wkseguimientos.netlify.app",
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