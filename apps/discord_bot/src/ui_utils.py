import hikari

class UIColors:
    GOLD = 0xF1C40F
    GREEN = 0x2ECC71
    BLUE = 0x3498DB
    ORANGE = 0xE67E22
    RED = 0xE74C3C
    STEAM_DARK = 0x1B2838
    PANEL_BLUE = 0x2B6CB0
    PROFILE_DARK = 0x2B2D31

def format_api_error(e: Exception) -> str:
    """Extrae el mensaje de error de las excepciones de la API de forma amigable"""
    err_str = str(e)
    if "HTTP 40" in err_str or "HTTP 50" in err_str or ("detail" in err_str and ":" in err_str):
        return err_str.split(":", 1)[-1].strip()
    return err_str
