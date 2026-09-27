import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# =========================================================
# 1. ARRANCAR EL SERVIDOR WEB AL INSTANTE (PRIMERA LÍNEA)
# =========================================================
class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Bot activo y respondiendo peticiones")

    def log_message(self, format, *args):
        return  # Silencia los logs de pings repetitivos en la consola

def iniciar_servidor_web():
    puerto = int(os.environ.get("PORT", 10000))
    servidor = HTTPServer(("0.0.0.0", puerto), KeepAliveHandler)
    print(f"📡 Servidor HTTP Keep-Alive abierto con exito en el puerto {puerto}")
    servidor.serve_forever()

hilo_servidor = threading.Thread(target=iniciar_servidor_web, daemon=True)
hilo_servidor.start()

# =========================================================
# 2. IMPORTS DEL PROYECTO
# =========================================================
import discord
from discord.ext import commands
from discord.ext import voice_recv
from discord import app_commands
import yt_dlp
import asyncio
import shutil
import tempfile
from dotenv import load_dotenv

load_dotenv()

# =========================================================
# 3. LÓGICA DE TU BOT DE MÚSICA
# =========================================================
def load_opus_lib():
    if not discord.opus.is_loaded():
        try:
            discord.opus.load_opus('libopus.so.0')
        except Exception as e:
            print(f"Error cargando opus de forma nativa: {e}")

# CORRECCIÓN AQUÍ: Cambiado voice_recv.VoiceRecvSink por voice_recv.AudioSink
class VoiceActivitySink(voice_recv.AudioSink):
    def __init__(self):
        super().__init__()
    def want_opus(self):
        return True
    def write(self, user, data):
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
    'default_search': 'auto',
    'source_address': '0.0.0.0',
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

@bot.tree.command(name="join", description="Une al bot a tu canal de voz actual.")
async def join(interaction: discord.Interaction):
    if not interaction.user.voice:
        await interaction.response.send_message("❌ ¡Debes estar en un canal de voz para usar este comando!", ephemeral=True)
        return
    channel = interaction.user.voice.channel
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.move_to(channel)
    else:
        # Se requiere VoiceRecvClient para habilitar la recepción de voz en canales
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

    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        try:
            info = ydl.extract_info(busqueda, download=False)
            if 'entries' in info:
                info = info['entries']
            url = info['url']
            titulo = info['title']
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
# 4. EJECUCIÓN FINAL DE DISCORD
# =========================================================
bot.run(os.getenv("DISCORD_TOKEN"))
