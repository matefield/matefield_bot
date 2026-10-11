import logging

import colorlog
import crescent
import hikari
from wardogs_config import BOT_SETTINGS

from src.model import Model

# Configurar logs coloridos
handler = colorlog.StreamHandler()
handler.setFormatter(colorlog.ColoredFormatter(
    '%(log_color)s[%(asctime)s] [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S',
    log_colors={
        'DEBUG': 'cyan',
        'INFO': 'green',
        'WARNING': 'yellow',
        'ERROR': 'red',
        'CRITICAL': 'bold_red',
    }
))

logger = colorlog.getLogger("wardogs")
logger.addHandler(handler)
logger.setLevel(logging.INFO)
# Hikari ya tiene sus propios logs, los dejamos en INFO o WARNING si queremos menos ruido
logging.getLogger("hikari").setLevel(logging.WARNING)

bot = hikari.GatewayBot(
    BOT_SETTINGS.DISCORD_TOKEN,
    intents=hikari.Intents.ALL_UNPRIVILEGED | hikari.Intents.GUILD_MEMBERS | hikari.Intents.GUILD_PRESENCES
)
model = Model()
client = crescent.Client(bot, model)

# Cargar plugins (aqui cargaremos los comandos)
client.plugins.load_folder("src.plugins")
if not BOT_SETTINGS.DISCORD_MEMBERSHIP_MANAGEMENT_ENABLED:
    client.plugins.unload("src.plugins.memberships")
    logger.info("Membership commands and roles are managed by Laracord.")

if __name__ == "__main__":
    if BOT_SETTINGS.DISCORD_TOKEN in ("tu_token_aqui", "", None):
        print("Error: Por favor configura el DISCORD_TOKEN en el archivo .env")
    else:
        bot.run()
