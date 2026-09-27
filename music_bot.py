import os
import shutil
import threading

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
import copy
from yt_dlp import utils as ytdlp_utils
from dotenv import load_dotenv

load_dotenv()

TEMP_DIR = "temp_audio"
if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)

# Copiamos las cookies secretas de Render a la carpeta temporal
COOKIES_PATH = os.path.join(TEMP_DIR, "cookies.txt")
ORIGINAL_COOKIES = "/etc/secrets/cookies.txt"

COOKIES_DISPONIBLES = False
if os.path.exists(ORIGINAL_COOKIES):
    try:
        shutil.copy(ORIGINAL_COOKIES, COOKIES_PATH)
        COOKIES_DISPONIBLES = True
        print("✅ Cookies copiadas correctamente a la zona de escritura temporal.")
    except Exception as e:
        print(f"⚠️ Error copiando cookies: {e}")
else:
    print("⚠️ Advertencia: No se encontró el archivo de cookies en /etc/secrets/cookies.txt")

# =========================================================
# 3. CONFIGURACIÓN DE YT-DLP (CORREGIDA)
# =========================================================
def load_opus_lib():
    if not discord.opus.is_loaded():
        for lib in ['libopus.so.0', 'libopus.so', 'opus']:
            try:
                discord.opus.load_opus(lib)
                print(f"✅ Librería Opus cargada: {lib}")
                return
            except Exception:
                continue
        print("⚠️ No se pudo cargar Opus. La reproducción podría fallar.")


def construir_opciones_base(player_client=None):
    """
    Construye las opciones base de yt-dlp.
    Se puede personalizar el player_client para cada variante.
    """
    opts = {
        'noplaylist': True,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'quiet': True,
        'no_warnings': True,
        'source_address': '0.0.0.0',
        'socket_timeout': 20,
        'retries': 5,
        'extractor_retries': 5,
        'file_access_retries': 5,
        'fragment_retries': 5,
        'nocheckcertificate': True,
        'geo_bypass': True,
        'extractor_args': {
            'youtube': {
                'player_client': player_client or ['android'],
                'skip': ['hls', 'dash'],
            }
        },
    }
    
    # Solo añadir cookies si están disponibles
    if COOKIES_DISPONIBLES:
        opts['cookiefile'] = COOKIES_PATH
    
    return opts


# Variantes de fallback (de más específica a más permisiva)
def generar_variantes():
    """
    Genera las variantes de configuración a probar en orden.
    Cada variante es una tupla (nombre, opciones, formato).
    """
    variantes = []
    
    # --- Variante 1: Android con bestaudio (preferida) ---
    v = construir_opciones_base(['android'])
    v['format'] = 'bestaudio'
    variantes.append(("android + bestaudio", v))
    
    # --- Variante 2: Android con bestaudio/best ---
    v = construir_opciones_base(['android'])
    v['format'] = 'bestaudio/best'
    variantes.append(("android + bestaudio/best", v))
    
    # --- Variante 3: iOS con bestaudio ---
    v = construir_opciones_base(['ios'])
    v['format'] = 'bestaudio'
    variantes.append(("ios + bestaudio", v))
    
    # --- Variante 4: Android sin filtro de formato ---
    v = construir_opciones_base(['android'])
    v.pop('format', None)
    variantes.append(("android + sin filtro", v))
    
    # --- Variante 5: Web con bestaudio (requiere PO token en algunos casos) ---
    v = construir_opciones_base(['web'])
    v['format'] = 'bestaudio/best'
    variantes.append(("web + bestaudio/best", v))
    
    # --- Variante 6: Múltiples clientes con formatos específicos ---
    v = construir_opciones_base(['android', 'ios', 'web'])
    v['format'] = 'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best'
    variantes.append(("multi-cliente + m4a/webm", v))
    
    # --- Variante 7: Última opción, cualquier cosa con audio ---
    v = construir_opciones_base(['android'])
    v['format'] = 'worstaudio/worst'
    variantes.append(("android + worstaudio (último recurso)", v))
    
    return variantes


def extraer_info_con_fallback(query):
    """
    Intenta extraer información del video probando múltiples variantes.
    Devuelve (stream_url, titulo) o lanza excepción con detalles.
    """
    errores = []
    
    for nombre, opts in generar_variantes():
        try:
            print(f"🔄 Probando variante: {nombre}")
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(query, download=False)
            
            # Si es una búsqueda, tomar la primera entrada válida
            if isinstance(info, dict) and 'entries' in info:
                entries = [e for e in (info.get('entries') or []) if e]
                if not entries:
                    errores.append(f"[{nombre}] Sin resultados")
                    continue
                info = entries[0]
            
            if not info:
                errores.append(f"[{nombre}] Info vacío")
                continue
            
            titulo = info.get('title', 'Audio desconocido')
            stream_url = None
            
            # --- Estrategia 1: buscar en formats el mejor audio-only ---
            formats = info.get('formats') or []
            if formats:
                # Filtrar solo-audio con URL válida
                audio_only = [
                    f for f in formats
                    if f.get('url')
                    and f.get('acodec') and f.get('acodec') != 'none'
                    and (not f.get('vcodec') or f.get('vcodec') == 'none')
                ]
                
                if audio_only:
                    # Preferir opus (mejor para Discord)
                    opus = next(
                        (f for f in audio_only if f.get('acodec') == 'opus'),
                        None
                    )
                    if opus and opus.get('url'):
                        stream_url = opus['url']
                        print(f"   ✅ Opus encontrado")
                    else:
                        # Si no hay opus, elegir mayor bitrate
                        best = max(
                            audio_only,
                            key=lambda f: (f.get('abr') or f.get('tbr') or 0)
                        )
                        if best.get('url'):
                            stream_url = best['url']
                            print(f"   ✅ {best.get('acodec')} @ {best.get('abr')}kbps")
                
                # Si aún no hay, buscar cualquier formato con audio
                if not stream_url:
                    con_audio = [
                        f for f in formats
                        if f.get('url') and f.get('acodec') and f.get('acodec') != 'none'
                    ]
                    if con_audio:
                        best = max(
                            con_audio,
                            key=lambda f: (f.get('abr') or f.get('tbr') or 0)
                        )
                        if best.get('url'):
                            stream_url = best['url']
                            print(f"   ✅ Formato con video (fallback)")
            
            # --- Estrategia 2: URL raíz ---
            if not stream_url and info.get('url'):
                stream_url = info['url']
                print(f"   ✅ URL raíz del info")
            
            if stream_url:
                return stream_url, titulo
            else:
                errores.append(f"[{nombre}] No se encontró URL de streaming")
                
        except ytdlp_utils.DownloadError as e:
            msg = str(e)
            errores.append(f"[{nombre}] DownloadError: {msg[:120]}")
            print(f"   ❌ {msg[:100]}")
            continue
        except Exception as e:
            msg = str(e)
            errores.append(f"[{nombre}] {type(e).__name__}: {msg[:120]}")
            print(f"   ❌ {type(e).__name__}: {msg[:100]}")
            continue
    
    # Si todas fallaron
    detalle = "\n".join(f"  - {e}" for e in errores)
    raise Exception(
        f"❌ No se pudo obtener el stream tras {len(errores)} intentos.\n"
        f"Detalles:\n{detalle}\n\n"
        f"💡 Soluciones:\n"
        f"  1. Actualiza yt-dlp: pip install --upgrade yt-dlp\n"
        f"  2. Verifica que las cookies no estén caducadas\n"
        f"  3. Prueba con otro video para descartar bloqueo del mismo"
    )


def obtener_stream_url_sync(query):
    """Wrapper sincrónico para ejecutar en executor."""
    return extraer_info_con_fallback(query)


def debug_formats(video_id):
    """
    Función de diagnóstico: lista todos los formatos disponibles.
    Ejecutar manualmente para debug.
    """
    print(f"\n🔍 Diagnóstico para video: {video_id}\n")
    try:
        opts = construir_opciones_base(['android'])
        opts['listformats'] = True
        opts['quiet'] = False
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(
                f'https://www.youtube.com/watch?v={video_id}',
                download=False
            )
    except Exception as e:
        print(f"❌ Error en diagnóstico: {e}")


# =========================================================
# 4. BOT DE DISCORD
# =========================================================
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
        print("✅ Bot iniciado y comandos de barra sincronizados.")


bot = MusicBot()


FFMPEG_OPTIONS = {
    'before_options': (
        '-reconnect 1 '
        '-reconnect_streamed 1 '
        '-reconnect_delay_max 5 '
        '-nostdin'
    ),
    'options': '-vn -b:a 192k',
}


# =========================================================
# 5. COMANDOS
# =========================================================
@bot.tree.command(name="join", description="Une al bot a tu canal de voz actual.")
async def join(interaction: discord.Interaction):
    if not interaction.user.voice:
        await interaction.response.send_message(
            "❌ ¡Debes estar en un canal de voz!",
            ephemeral=True
        )
        return
    
    channel = interaction.user.voice.channel
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.move_to(channel)
    else:
        await channel.connect(cls=voice_recv.VoiceRecvClient)
    
    await interaction.response.send_message(f"✅ Me he unido a **{channel.name}**")


@bot.tree.command(name="play", description="Reproduce música de YouTube.")
@app_commands.describe(busqueda="Nombre de la canción o enlace de YouTube")
async def play(interaction: discord.Interaction, busqueda: str):
    await interaction.response.send_message(
        f"⏳ Buscando: **{busqueda}**...",
        ephemeral=False
    )
    
    # Conectar al canal si no lo está
    if not interaction.guild.voice_client:
        if interaction.user.voice:
            try:
                await interaction.user.voice.channel.connect(cls=voice_recv.VoiceRecvClient)
            except Exception as e:
                await interaction.edit_original_response(
                    content=f"❌ No pude conectarme al canal: {e}"
                )
                return
        else:
            await interaction.edit_original_response(
                content="❌ ¡Debes estar en un canal de voz!"
            )
            return
    
    vc = interaction.guild.voice_client
    
    # Construir query
    query = busqueda
    if not busqueda.startswith(("http://", "https://")):
        query = f"ytsearch1:{busqueda}"
    
    # Extraer URL del stream
    try:
        loop = asyncio.get_event_loop()
        stream_url, titulo = await asyncio.wait_for(
            loop.run_in_executor(None, obtener_stream_url_sync, query),
            timeout=120.0
        )
    except asyncio.TimeoutError:
        await interaction.edit_original_response(
            content="❌ Tiempo de espera agotado (YouTube tardó demasiado)."
        )
        return
    except Exception as e:
        error_msg = str(e)
        # Limitar longitud para Discord (2000 caracteres)
        if len(error_msg) > 1800:
            error_msg = error_msg[:1800] + "..."
        await interaction.edit_original_response(
            content=f"```\n{error_msg}\n```"
        )
        return
    
    # Reproducir
    def after_playing(error):
        if error:
            print(f"⚠️ Error en reproducción: {error}")
    
    try:
        if vc.is_playing():
            vc.stop()
        
        source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)
        vc.play(source, after=after_playing)
        await interaction.edit_original_response(
            content=f"🎵 Reproduciendo: **{titulo}**"
        )
    except Exception as e:
        await interaction.edit_original_response(
            content=f"❌ Error al reproducir: {e}"
        )


@bot.tree.command(name="background", description="Escucha el canal en segundo plano.")
async def background(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if not vc:
        await interaction.response.send_message(
            "❌ El bot no está conectado a ningún canal.",
            ephemeral=True
        )
        return
    try:
        vc.listen(VoiceActivitySink())
        await interaction.response.send_message(
            "🎙️ Modo escucha activado."
        )
    except Exception as e:
        await interaction.response.send_message(
            f"❌ Error: {e}",
            ephemeral=True
        )


@bot.tree.command(name="leave", description="Desconecta al bot del canal.")
async def leave(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc:
        await vc.disconnect()
        await interaction.response.send_message("👋 Desconectado.")
    else:
        await interaction.response.send_message(
            "❌ No estoy en ningún canal.",
            ephemeral=True
        )


@bot.tree.command(name="debug", description="Diagnostica un video de YouTube.")
@app_commands.describe(video_id="ID del video (ej: joaZxKoA7_M)")
async def debug(interaction: discord.Interaction, video_id: str):
    await interaction.response.defer(ephemeral=True)
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, debug_formats, video_id)
        await interaction.followup.send(
            "✅ Diagnóstico completado. Revisa los logs del bot.",
            ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)


# =========================================================
# 6. EJECUCIÓN
# =========================================================
if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("❌ ERROR: DISCORD_TOKEN no configurado")
        exit(1)
    bot.run(token)
