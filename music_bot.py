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
# 3. LÓGICA DE TU BOT DE MÚSICA (Streaming con ordenamiento sort (-S) universal)
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

# Opciones de yt-dlp: pedir el mejor audio disponible; la función de extracción implementa fallbacks
YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'quiet': True,
    'no_warnings': True,
    'source_address': '0.0.0.0',
    'socket_timeout': 10,
    'cookiefile': COOKIES_PATH,
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'web']
        }
    }
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -b:a 192k',
}

def obtener_stream_url_sync(query):
    """
    Extrae una URL directa de streaming desde yt-dlp seleccionando un formato de audio adecuado.
    Implementa varias variantes/fallbacks para evitar el error "Requested format is not available".
    """
    import copy
    from yt_dlp import utils as ytdlp_utils

    variantes = []
    # 1) Opciones preferidas (bestaudio)
    variantes.append(copy.deepcopy(YDL_OPTIONS))

    # 2) Fallback: priorizar webm opus si existe
    fb1 = copy.deepcopy(YDL_OPTIONS)
    fb1['format'] = 'bestaudio[ext=webm]/bestaudio/best'
    variantes.append(fb1)

    # 3) Fallback final: eliminar el filtro de formato completamente
    fb2 = copy.deepcopy(YDL_OPTIONS)
    if 'format' in fb2:
        del fb2['format']
    variantes.append(fb2)

    last_error = None

    for opts in variantes:
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(query, download=False)
        except ytdlp_utils.DownloadError as e:
            last_error = str(e)
            # Si es un error de formato pedimos la siguiente variante
            if 'Requested format is not available' in last_error or 'format not available' in last_error:
                continue
            # Otros errores, re-lanzamos para que el caller los vea
            raise Exception(f"yt-dlp error: {e}")
        except Exception as e:
            last_error = str(e)
            # Intentar siguiente variante
            continue

        # Si es una búsqueda, tomar la primera entrada
        if isinstance(info, dict) and 'entries' in info:
            if not info['entries']:
                raise Exception("No se encontraron resultados en YouTube.")
            info = info['entries'][0]

        titulo = info.get('title', 'Audio desconocido')

        # Preferir una URL desde formats si está disponible
        formats = info.get('formats') or []
        if formats:
            audio_formats = [
                f for f in formats
                if f.get('url') and f.get('acodec') and f.get('acodec') != 'none'
            ]
            if audio_formats:
                # Preferir opus (audio-only), luego mayor bitrate
                opus = next((f for f in audio_formats if f.get('acodec') == 'opus' and (not f.get('vcodec') or f.get('vcodec') == 'none')), None)
                if opus:
                    stream_url = opus.get('url')
                else:
                    stream_url = max(audio_formats, key=lambda f: (f.get('abr') or f.get('tbr') or 0)).get('url')
                return stream_url, titulo

        # Fallback: usar URL raíz
        stream_url = info.get('url')
        if stream_url:
            return stream_url, titulo

    # Si llegamos aquí, todas las variantes fallaron
    raise Exception(f"No fue posible determinar una URL de streaming válida. Último error: {last_error}")

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

@bot.tree.command(name="play", description="Reproduce música de YouTube en streaming directo.")
@app_commands.describe(busqueda="Nombre de la canción o enlace de YouTube")
async def play(interaction: discord.Interaction, busqueda: str):
    await interaction.response.send_message(f"⏳ Conectando stream de YouTube: **{busqueda}**...", ephemeral=False)
    
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
        stream_url, titulo = await asyncio.wait_for(
            loop.run_in_executor(None, obtener_stream_url_sync, query), 
            timeout=12.0
        )
    except asyncio.TimeoutError:
        await interaction.edit_original_response(content="❌ Tiempo de espera agotado: YouTube tardó demasiado en responder y se canceló la conexión.")
        return
    except Exception as e:
        await interaction.edit_original_response(content=f"❌ Error al obtener el stream de YouTube: {e}")
        return

    def after_playing(error):
        if error:
            print(f"Error en reproducción: {error}")

    try:
        if vc.is_playing():
            vc.stop()
        
        source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)
        vc.play(source, after=after_playing)
        await interaction.edit_original_response(content=f"🎵 Reproduciendo en vivo: **{titulo}**")
    except Exception as e:
        await interaction.edit_original_response(content=f"❌ Error al iniciar el streaming: {e}")

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
