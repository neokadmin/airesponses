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
# 2. IMPORTS
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

# =========================================================
# 3. CONFIGURACIÓN SOUNDCLOUD
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


# Opciones base para SoundCloud
YDL_OPTIONS_SC = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'quiet': True,
    'no_warnings': True,
    'source_address': '0.0.0.0',
    'socket_timeout': 20,
    'retries': 5,
    'extractor_retries': 5,
    'fragment_retries': 5,
    'geo_bypass': True,
    # SoundCloud suele funcionar bien con user-agent de navegador
    'http_headers': {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        ),
        'Accept-Language': 'en-US,en;q=0.9',
    },
}


def es_error_drm_o_no_disponible(msg: str) -> bool:
    """
    Detecta si el error indica DRM, track no disponible o restricción.
    En esos casos, saltamos al siguiente resultado sin mostrar error al usuario.
    """
    msg_lower = msg.lower()
    palabras_clave = [
        'drm',
        'not available',
        'unavailable',
        'copyright',
        'geo',
        'blocked',
        'no video formats',
        'no formats',
        'requested format is not available',
        'unable to extract',
        'private',
        'removed',
        'deleted',
        'not playable',
        'unsupported',
        'preview only',
        'snippet',
    ]
    return any(k in msg_lower for k in palabras_clave)


def extraer_info_sc(query: str, max_intentos: int = 10):
    """
    Busca en SoundCloud y prueba los primeros N resultados en orden.
    Si un resultado falla por DRM o no disponible, pasa al siguiente.
    Devuelve (stream_url, titulo) del primer track reproducible.
    
    Si 'query' es una URL directa de SoundCloud, se prueba solo esa.
    Si es texto, se hace búsqueda tipo scsearchN.
    """
    # Determinar si es URL directa o búsqueda
    es_url = query.startswith(('http://', 'https://'))
    
    if es_url:
        # URL directa: probar solo esa
        queries_a_probar = [query]
    else:
        # Búsqueda: pedir varios resultados y probar en orden
        queries_a_probar = [f'scsearch{max_intentos}:{query}']
    
    errores = []
    
    for q in queries_a_probar:
        try:
            print(f"🔍 Buscando en SoundCloud: {q[:80]}")
            with yt_dlp.YoutubeDL(YDL_OPTIONS_SC) as ydl:
                info = ydl.extract_info(q, download=False)
        except Exception as e:
            # Error al hacer la búsqueda misma
            msg = str(e)
            if es_error_drm_o_no_disponible(msg):
                errores.append(f"Búsqueda falló: {msg[:100]}")
                continue
            errores.append(f"Error de búsqueda: {msg[:100]}")
            continue
        
        if not info:
            errores.append("Info vacío")
            continue
        
        # Si es una búsqueda con múltiples entries, probar cada una
        if isinstance(info, dict) and 'entries' in info:
            entries = [e for e in (info.get('entries') or []) if e]
            if not entries:
                errores.append("Sin resultados en SoundCloud")
                continue
            
            print(f"📋 {len(entries)} resultados encontrados. Probando en orden...")
            
            for idx, entry in enumerate(entries):
                try:
                    titulo = entry.get('title', f'Track {idx+1}')
                    url_track = entry.get('webpage_url') or entry.get('url')
                    
                    if not url_track:
                        errores.append(f"[{idx+1}] {titulo}: sin URL")
                        continue
                    
                    print(f"   🎵 [{idx+1}/{len(entries)}] Probando: {titulo}")
                    
                    # Extraer info completa del track individual
                    try:
                        with yt_dlp.YoutubeDL(YDL_OPTIONS_SC) as ydl2:
                            info_track = ydl2.extract_info(url_track, download=False)
                    except Exception as e:
                        msg = str(e)
                        if es_error_drm_o_no_disponible(msg):
                            print(f"   ⚠️ DRM/No disponible: {titulo}")
                            errores.append(f"[{idx+1}] {titulo}: DRM/No disponible")
                        else:
                            print(f"   ⚠️ Error: {msg[:80]}")
                            errores.append(f"[{idx+1}] {titulo}: {msg[:80]}")
                        continue  # ← Pasar al siguiente resultado
                    
                    if not info_track:
                        errores.append(f"[{idx+1}] {titulo}: info vacío")
                        continue
                    
                    stream_url = _obtener_mejor_url(info_track)
                    
                    if stream_url:
                        titulo_final = info_track.get('title', titulo)
                        print(f"   ✅ Reproducible: {titulo_final}")
                        return stream_url, titulo_final
                    else:
                        errores.append(f"[{idx+1}] {titulo}: sin URL de audio")
                        continue
                        
                except Exception as e:
                    errores.append(f"[{idx+1}] Error: {str(e)[:80]}")
                    continue
        
        # Si info es un track único (URL directa)
        else:
            titulo = info.get('title', 'Audio desconocido')
            stream_url = _obtener_mejor_url(info)
            if stream_url:
                return stream_url, titulo
            else:
                errores.append(f"{titulo}: sin URL de audio")
    
    # Si llegamos aquí, ningún resultado funcionó
    detalle = "\n".join(f"  - {e}" for e in errores[-8:])  # últimos 8
    raise Exception(
        f"❌ No se encontró ningún track reproducible en SoundCloud.\n"
        f"Se intentaron varios resultados sin éxito.\n"
        f"Detalles:\n{detalle}"
    )


def _obtener_mejor_url(info: dict):
    """
    Extrae la mejor URL de audio del info de yt-dlp.
    Prioriza opus (mejor para Discord), luego mayor bitrate.
    """
    formats = info.get('formats') or []
    
    if formats:
        # Filtrar formatos con URL y códec de audio
        audio_formats = [
            f for f in formats
            if f.get('url') and f.get('acodec') and f.get('acodec') != 'none'
        ]
        
        if audio_formats:
            # Preferir opus
            opus = next(
                (f for f in audio_formats if f.get('acodec') == 'opus'),
                None
            )
            if opus and opus.get('url'):
                return opus['url']
            
            # Si no hay opus, el de mayor bitrate
            best = max(
                audio_formats,
                key=lambda f: (f.get('abr') or f.get('tbr') or 0)
            )
            if best.get('url'):
                return best['url']
    
    # Fallback: URL raíz
    return info.get('url')


def obtener_stream_url_sync(query):
    """Wrapper sincrónico para ejecutar en executor."""
    return extraer_info_sc(query)


def debug_sc(query):
    """Diagnóstico: lista formatos de un track de SoundCloud."""
    print(f"\n🔍 Diagnóstico SoundCloud: {query}\n")
    try:
        with yt_dlp.YoutubeDL({**YDL_OPTIONS_SC, 'listformats': True, 'quiet': False}) as ydl:
            ydl.extract_info(query, download=False)
    except Exception as e:
        print(f"❌ Error: {e}")


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
        print("✅ Bot iniciado y comandos sincronizados.")


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
@bot.tree.command(name="join", description="Une al bot a tu canal de voz.")
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
    
    await interaction.response.send_message(f"✅ Me uní a **{channel.name}**")


@bot.tree.command(name="play", description="Reproduce música desde SoundCloud.")
@app_commands.describe(busqueda="Nombre de la canción o enlace de SoundCloud")
async def play(interaction: discord.Interaction, busqueda: str):
    await interaction.response.send_message(
        f"⏳ Buscando en SoundCloud: **{busqueda}**...",
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
    
    # Extraer URL del stream con fallback automático
    try:
        loop = asyncio.get_event_loop()
        stream_url, titulo = await asyncio.wait_for(
            loop.run_in_executor(None, obtener_stream_url_sync, busqueda),
            timeout=150.0
        )
    except asyncio.TimeoutError:
        await interaction.edit_original_response(
            content="❌ Tiempo de espera agotado buscando en SoundCloud."
        )
        return
    except Exception as e:
        error_msg = str(e)
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
        await interaction.response.send_message("🎙️ Modo escucha activado.")
    except Exception as e:
        await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)


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


@bot.tree.command(name="debug", description="Diagnostica un track de SoundCloud.")
@app_commands.describe(url="URL del track de SoundCloud")
async def debug(interaction: discord.Interaction, url: str):
    await interaction.response.defer(ephemeral=True)
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, debug_sc, url)
        await interaction.followup.send(
            "✅ Diagnóstico completado. Revisa los logs.",
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
