# backend/utils/pin_utils.py
import random
import string


def generar_pin_2letras_3numeros() -> str:
    """
    Genera un PIN tipo: AA123 (2 letras mayúsculas + 3 números).
    Ejemplo: QF482
    """
    letras = ''.join(random.choices(string.ascii_uppercase, k=2))
    numeros = ''.join(random.choices(string.digits, k=3))
    return f"{letras}{numeros}"


