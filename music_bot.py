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
import copy
from yt_dlp import utils as ytdlp_utils
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
            print("✅ Librería Opus cargada correctamente.")
        except Exception as e:
            print(f"⚠️ Error cargando opus de forma nativa: {e}")

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

# =========================================================
# OPCIONES DE YT-DLP (CORREGIDAS)
# =========================================================
# ⚠️ CAMBIO CLAVE: Se eliminó 'web' de player_client porque ahora requiere
# un PO Token que yt-dlp no puede generar automáticamente. El cliente
# 'android' es el más estable para obtener streams de audio.
YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'quiet': True,
    'no_warnings': True,
    'source_address': '0.0.0.0',
    'socket_timeout': 15,
    'cookiefile': COOKIES_PATH if os.path.exists(COOKIES_PATH) else None,
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'ios'],  # Android + iOS como respaldo
            'skip': ['hls', 'dash'],  # Saltar formatos fragmentados problemáticos
        }
    },
    # Opciones extra para mayor compatibilidad
    'extractor_retries': 3,
    'file_access_retries': 3,
    'fragment_retries': 3,
}

# Limpiar cookiefile si no existe para evitar warnings
if not YDL_OPTIONS['cookiefile']:
    del YDL_OPTIONS['cookiefile']

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin',
    'options': '-vn -b:a 192k',
}


def obtener_stream_url_sync(query):
    """
    Extrae una URL directa de streaming desde yt-dlp con múltiples fallbacks.
    Corrige el error "Requested format is not available" probando diferentes
    configuraciones de formatos y clientes de YouTube.
    """
    
    # Definimos las variantes de configuración a probar (de más específica a más general)
    variantes = []
    
    # Variante 1: bestaudio puro (preferido)
    v1 = copy.deepcopy(YDL_OPTIONS)
    v1['format'] = 'bestaudio'
    variantes.append(("bestaudio", v1))
    
    # Variante 2: bestaudio con fallback a best
    v2 = copy.deepcopy(YDL_OPTIONS)
    v2['format'] = 'bestaudio/best'
    variantes.append(("bestaudio/best", v2))
    
    # Variante 3: cualquier audio disponible (m4a, webm, etc.)
    v3 = copy.deepcopy(YDL_OPTIONS)
    v3['format'] = 'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio'
    variantes.append(("bestaudio m4a/webm", v3))
    
    # Variante 4: sin filtro de formato (el más permisivo)
    v4 = copy.deepcopy(YDL_OPTIONS)
    v4.pop('format', None)
    variantes.append(("sin filtro de formato", v4))
    
    # Variante 5: cambiar cliente a ios si android falla
    v5 = copy.deepcopy(YDL_OPTIONS)
    v5['format'] = 'bestaudio/best'
    v5['extractor_args'] = {'youtube': {'player_client': ['ios']}}
    variantes.append(("cliente ios", v5))
    
    # Variante 6: cliente web como último recurso
    v6 = copy.deepcopy(YDL_OPTIONS)
    v6['format'] = 'bestaudio/best'
    v6['extractor_args'] = {'youtube': {'player_client': ['web']}}
    variantes.append(("cliente web", v6))

    last_error = None
    errores_detalle = []

    for nombre, opts in variantes:
        try:
            print(f"🔄 Intentando variante: {nombre}")
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(query, download=False)
        except ytdlp_utils.DownloadError as e:
            last_error = str(e)
            errores_detalle.append(f"[{nombre}] {last_error[:100]}")
            print(f"❌ Variante '{nombre}' falló: {last_error[:100]}")
            continue
        except Exception as e:
            last_error = str(e)
            errores_detalle.append(f"[{nombre}] {last_error[:100]}")
            print(f"❌ Variante '{nombre}' error inesperado: {last_error[:100]}")
            continue

        # Si es una búsqueda tipo ytsearch1:, tomar la primera entrada
        if isinstance(info, dict) and 'entries' in info:
            entries = [e for e in (info.get('entries') or []) if e]
            if not entries:
                errores_detalle.append(f"[{nombre}] Sin resultados de búsqueda")
                continue
            info = entries[0]

        if not info:
            errores_detalle.append(f"[{nombre}] info vacío")
            continue

        titulo = info.get('title', 'Audio desconocido')
        stream_url = None

        # 1) Intentar obtener URL directa de los formatos
        formats = info.get('formats') or []
        if formats:
            # Filtrar formatos solo-audio (sin video) y con URL válida
            audio_only = [
                f for f in formats
                if f.get('url')
                and f.get('acodec') and f.get('acodec') != 'none'
                and (not f.get('vcodec') or f.get('vcodec') == 'none')
            ]
            
            if audio_only:
                # Preferir opus por su menor latencia en Discord
                opus = next(
                    (f for f in audio_only if f.get('acodec') == 'opus'),
                    None
                )
                if opus:
                    stream_url = opus.get('url')
                    print(f"✅ Variante '{nombre}': usando formato Opus")
                else:
                    # Si no hay opus, elegir el de mayor bitrate
                    best = max(
                        audio_only,
                        key=lambda f: (f.get('abr') or f.get('tbr') or 0)
                    )
                    stream_url = best.get('url')
                    print(f"✅ Variante '{nombre}': usando {best.get('acodec')} a {best.get('abr')}kbps")
            
            # Si no hay solo-audio, intentar cualquier cosa con audio
            if not stream_url:
                with_audio = [
                    f for f in formats
                    if f.get('url') and f.get('acodec') and f.get('acodec') != 'none'
                ]
                if with_audio:
                    best = max(
                        with_audio,
                        key=lambda f: (f.get('abr') or f.get('tbr') or 0)
                    )
                    stream_url = best.get('url')
                    print(f"✅ Variante '{nombre}': usando formato con video (fallback)")
        
        # 2) Fallback: URL raíz del info
        if not stream_url:
            stream_url = info.get('url')
            if stream_url:
                print(f"✅ Variante '{nombre}': usando URL raíz")

        if stream_url:
            return stream_url, titulo
        else:
            errores_detalle.append(f"[{nombre}] No se encontró URL de streaming")

    # Si todas las variantes fallaron, lanzar excepción detallada
    detalle = "\n".join(errores_detalle) if errores_detalle else "Sin detalles"
    raise Exception(
        f"No se pudo obtener URL de streaming después de {len(variantes)} intentos.\n"
        f"Último error: {last_error}\n"
        f"Detalles:\n{detalle}"
    )


def debug_formats(video_id):
    """
    Función de diagnóstico: lista todos los formatos disponibles para un video.
    Útil para debug cuando 'Requested format is not available' persiste.
    """
    try:
        with yt_dlp.YoutubeDL({'quiet': False, 'listformats': True}) as ydl:
            ydl.extract_info(f'https://www.youtube.com/watch?v={video_id}', download=False)
    except Exception as e:
        print(f"Error en debug: {e}")


# =========================================================
# COMANDOS DEL BOT
# =========================================================
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
    await interaction.response.send_message(
        f"⏳ Conectando stream de YouTube: **{busqueda}**...",
        ephemeral=False
    )

    # Conectar al canal de voz si no lo está
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

    # Construir query
    query = busqueda
    if not busqueda.startswith("http://") and not busqueda.startswith("https://"):
        query = f"ytsearch1:{busqueda}"

    # Extraer URL de streaming
    try:
        loop = asyncio.get_event_loop()
        stream_url, titulo = await asyncio.wait_for(
            loop.run_in_executor(None, obtener_stream_url_sync, query),
            timeout=120.0
        )
    except asyncio.TimeoutError:
        await interaction.edit_original_response(
            content="❌ Tiempo de espera agotado: YouTube tardó demasiado en responder."
        )
        return
    except Exception as e:
        await interaction.edit_original_response(
            content=f"❌ Error al obtener el stream de YouTube:\n```\n{str(e)[:1500]}\n```"
        )
        return

    def after_playing(error):
        if error:
            print(f"Error en reproducción: {error}")

    # Reproducir
    try:
        if vc.is_playing():
            vc.stop()

        source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)
        vc.play(source, after=after_playing)
        await interaction.edit_original_response(
            content=f"🎵 Reproduciendo en vivo: **{titulo}**"
        )
    except Exception as e:
        await interaction.edit_original_response(
            content=f"❌ Error al iniciar el streaming: {e}"
        )


@bot.tree.command(name="background", description="Escucha el canal de voz en segundo plano sin reproducir.")
async def background(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if not vc:
        await interaction.response.send_message(
            "❌ El bot no está conectado a ningún canal de voz.",
            ephemeral=True
        )
        return
    try:
        vc.listen(VoiceActivitySink())
        await interaction.response.send_message(
            "🎙️ Modo escucha en segundo plano activado correctamente."
        )
    except Exception as e:
        await interaction.response.send_message(
            f"❌ Error al activar el modo escucha: {e}",
            ephemeral=True
        )


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
