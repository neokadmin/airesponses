import os
import threading
import tempfile
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer

# =========================================================
# 0. ACTUALIZAR YT-DLP AUTOMÁTICAMENTE EN CADA INICIO (RENDER)
# =========================================================
try:
    print("🔄 Actualizando yt-dlp a la última versión para evitar errores de YouTube...")
    subprocess.run(["pip", "install", "--upgrade", "yt-dlp"], check=False)
except Exception as e:
    print(f"No se pudo actualizar yt-dlp automáticamente: {e}")

# =========================================================
# 1. SERVIDOR KEEP-ALIVE (Soporte UptimeRobot Gratis)
# =========================================================
class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Bot activo y respondiendo peticiones GET")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()

    def log_message(self, format, *args):
        return  # Silencia los logs de pings en la consola de Render

def iniciar_servidor_web():
    puerto = int(os.environ.get("PORT", 10000))
    servidor = HTTPServer(("0.0.0.0", puerto), KeepAliveHandler)
    print(f"📡 Servidor HTTP Keep-Alive (GET/HEAD) abierto en el puerto {puerto}")
    servidor.serve_forever()

hilo_servidor = threading.Thread(target=iniciar_servidor_web, daemon=True)
hilo_servidor.start()

# =========================================================
# 2. IMPORTS DEL PROYECTO DISCORD
# =========================================================
import discord
from discord.ext import commands
from discord.ext import voice_recv
from discord import app_commands
import yt_dlp
import asyncio
from dotenv import load_dotenv

load_dotenv()

# =========================================================
# 3. GESTIÓN DE COOKIES DESDE RENDER (ENV)
# =========================================================
def get_cookies_file():
    cookies_content = os.getenv("COOKIES_TXT")
    if cookies_content:
        temp_cookies = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt", encoding="utf-8")
        temp_cookies.write(cookies_content)
        temp_cookies.close()
        return temp_cookies.name
    elif os.path.exists('cookies.txt'):
        return 'cookies.txt'
    return None

COOKIE_PATH = get_cookies_file()

# =========================================================
# 4. LÓGICA DE TU BOT DE MÚSICA
# =========================================================
def load_opus_lib():
    if not discord.opus.is_loaded():
        try:
            discord.opus.load_opus('libopus.so.0')
        except Exception as e:
            print(f"Error cargando opus de forma nativa: {e}")

class VoiceActivitySink(voice_recv.AudioSink):
    def __init__(self):
        super().__init__()
    def wants_opus(self):
        return True
    def write(self, user, data):
        pass
    def cleanup(self):
        pass

class MusicBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        load_opus_lib()
        await self.tree.sync()
        print("Bot iniciado y comandos de barra (/) sincronizados.")

bot = MusicBot()

# Configuración actualizada con clientes alternativos y soporte de cookies obligatorias
YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'audioformat': 'mp3',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'source_address': '0.0.0.0',
    'socket_timeout': 10,  # <--- NUEVO: Si YouTube no responde en 10 segundos, corta y lanza error en vez de colgarse
    'cookiefile': COOKIE_PATH,
    'extractor_args': {
        'youtube': {
            'player_client': ['web', 'mweb', 'default']
        }
    }
}
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

def extraer_info_sync(query):
    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        return ydl.extract_info(query, download=False)

@bot.tree.command(name="join", description="Une al bot a tu canal de voz actual.")
async def join(interaction: discord.Interaction):
    if not interaction.user.voice:
        await interaction.response.send_message("❌ ¡Debes estar en un canal de voz para usar este comando!", ephemeral=True)
        return
    channel = interaction.user.voice.channel
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.move_to(channel)
    else:
        await channel.connect(cls=voice_recv.VoiceRecvClient)
    await interaction.response.send_message(f"✅ Me he unido a **{channel.name}**")

@bot.tree.command(name="play", description="Reproduce música desde una URL de YouTube o palabras clave.")
@app_commands.describe(busqueda="Enlace de YouTube o nombre de la canción")
async def play(interaction: discord.Interaction, busqueda: str):
    await interaction.response.defer()
    
    if not interaction.guild.voice_client:
        if interaction.user.voice:
            await interaction.user.voice.channel.connect(cls=voice_recv.VoiceRecvClient)
        else:
            await interaction.followup.send("❌ ¡Debes estar en un canal de voz!")
            return

    vc = interaction.guild.voice_client

    query = busqueda
    if not busqueda.startswith("http://") and not busqueda.startswith("https://"):
        query = f"ytsearch1:{busqueda}"

    try:
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, extraer_info_sync, query)
        
        if 'entries' in info:
            if not info['entries']:
                await interaction.followup.send("❌ No se encontraron resultados para tu búsqueda.")
                return
            video_data = info['entries'][0]
        else:
            video_data = info
            
        url = video_data['url']
        titulo = video_data['title']
    except Exception as e:
        await interaction.followup.send(f"❌ Error al procesar la búsqueda: {e}")
        return

    try:
        if vc.is_playing():
            vc.stop()
        
        source = discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS)
        vc.play(source)
        await interaction.followup.send(f"🎵 Reproduciendo ahora: **{titulo}**")
    except Exception as e:
        await interaction.followup.send(f"❌ Error al reproducir audio: {e}")

@bot.tree.command(name="background", description="Escucha el canal de voz en segundo plano sin reproducir.")
async def background(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if not vc:
        await interaction.response.send_message("❌ El bot no está conectado a ningún canal de voz.", ephemeral=True)
        return
    try:
        vc.listen(VoiceActivitySink())
        await interaction.response.send_message("🎙️ Modo escucha en segundo plano activado correctamente.")
    except Exception as e:
        await interaction.response.send_message(f"❌ Error al activar el modo escucha: {e}", ephemeral=True)

@bot.tree.command(name="leave", description="Desconecta al bot del canal de voz.")
async def leave(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc:
        await vc.disconnect()
        await interaction.response.send_message("👋 Desconectado exitosamente del canal de voz.")
    else:
        await interaction.response.send_message("❌ No estoy en ningún canal de voz.", ephemeral=True)

# =========================================================
# 5. EJECUCIÓN FINAL DE DISCORD
# =========================================================
bot.run(os.getenv("DISCORD_TOKEN"))
