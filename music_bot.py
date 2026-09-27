import os
import shutil
threading_mod = __import__('threading')

# =========================================================
# 1. SERVIDOR KEEP-ALIVE (Soporte UptimeRobot Gratis)
# =========================================================
from http.server import BaseHTTPRequestHandler, HTTPServer

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
        return

def iniciar_servidor_web():
    puerto = int(os.environ.get("PORT", 10000))
    servidor = HTTPServer(("0.0.0.0", puerto), KeepAliveHandler)
    print(f"📡 Servidor HTTP Keep-Alive abierto en el puerto {puerto}")
    servidor.serve_forever()

hilo_servidor = threading_mod.Thread(target=iniciar_servidor_web, daemon=True)
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

TEMP_DIR = "temp_audio"
if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)

# Copiamos las cookies secretas de Render a la carpeta temporal para evitar el error de solo lectura
COOKIES_PATH = os.path.join(TEMP_DIR, "cookies.txt")
ORIGINAL_COOKIES = "/etc/secrets/cookies.txt"

if os.path.exists(ORIGINAL_COOKIES):
    shutil.copy(ORIGINAL_COOKIES, COOKIES_PATH)
    print("✅ Cookies copiadas correctamente a la zona de escritura temporal.")
else:
    print("⚠️ Advertencia: No se encontró el archivo de cookies en /etc/secrets/cookies.txt")

# =========================================================
# 3. LÓGICA DE TU BOT DE MÚSICA
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

YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'outtmpl': os.path.join(TEMP_DIR, '%(id)s.%(ext)s'),
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'quiet': True,
    'no_warnings': True,
    'source_address': '0.0.0.0',
    'socket_timeout': 15,
    'cookiefile': COOKIES_PATH,  # <--- Usamos la copia editable
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'web']
        }
    }
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

def descargar_audio_sync(query):
    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        info = ydl.extract_info(query, download=True)
        if 'entries' in info:
            if not info['entries']:
                raise Exception("No se encontraron resultados en YouTube.")
            info = info['entries'][0]
        
        filename = ydl.prepare_filename(info)
        base, _ = os.path.splitext(filename)
        mp3_filename = base + ".mp3"
        
        return mp3_filename, info.get('title', 'Audio desconocido')

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

@bot.tree.command(name="play", description="Descarga y reproduce música de YouTube sin bloqueos.")
@app_commands.describe(busqueda="Nombre de la canción o enlace de YouTube")
async def play(interaction: discord.Interaction, busqueda: str):
    await interaction.response.send_message(f"⏳ Buscando en YouTube: **{busqueda}**...", ephemeral=False)
    
    if not interaction.guild.voice_client:
        if interaction.user.voice:
            try:
                await interaction.user.voice.channel.connect(cls=voice_recv.VoiceRecvClient)
            except Exception as e:
                await interaction.edit_original_response(content=f"❌ No pude conectarme al canal de voz: {e}")
                return
        else:
            await interaction.edit_original_response(content="❌ ¡Debes estar en un canal de voz!")
            return

    vc = interaction.guild.voice_client

    query = busqueda
    if not busqueda.startswith("http://") and not busqueda.startswith("https://"):
        query = f"ytsearch1:{busqueda}"

    try:
        loop = asyncio.get_event_loop()
        filepath, titulo = await loop.run_in_executor(None, descargar_audio_sync, query)
    except Exception as e:
        await interaction.edit_original_response(content=f"❌ Error al descargar de YouTube: {e}")
        return

    def after_playing(error):
        if error:
            print(f"Error en reproducción: {error}")
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                print(f"🗑️ Archivo temporal eliminado: {filepath}")
            except Exception as ex:
                print(f"No se pudo eliminar el archivo: {ex}")

    try:
        if vc.is_playing():
            vc.stop()
        
        source = discord.FFmpegPCMAudio(filepath, **FFMPEG_OPTIONS)
        vc.play(source, after=after_playing)
        await interaction.edit_original_response(content=f"🎵 Reproduciendo ahora: **{titulo}**")
    except Exception as e:
        await interaction.edit_original_response(content=f"❌ Error al iniciar el audio: {e}")
        if os.path.exists(filepath):
            os.remove(filepath)

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
# 4. EJECUCIÓN FINAL DE DISCORD
# =========================================================
bot.run(os.getenv("DISCORD_TOKEN"))
