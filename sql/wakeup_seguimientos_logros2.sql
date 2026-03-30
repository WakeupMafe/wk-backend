-- Encuesta de seguimiento (Logros 2) — ejecutar en Supabase SQL editor si aún no existe la tabla.

CREATE TABLE IF NOT EXISTS public.wakeup_seguimientos_logros2 (
  id_int BIGSERIAL PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  documento BIGINT NOT NULL,
  encuestador BIGINT NOT NULL,
  sede TEXT NOT NULL,
  id_encuesta_fase1 BIGINT NOT NULL,
  respuestas JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_logros2_documento ON public.wakeup_seguimientos_logros2 (documento);
CREATE INDEX IF NOT EXISTS idx_logros2_fase1 ON public.wakeup_seguimientos_logros2 (id_encuesta_fase1);

COMMENT ON TABLE public.wakeup_seguimientos_logros2 IS 'Seguimiento clínico post encuesta de logros (fase 1).';
