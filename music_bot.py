import os
import shutil
import threading

# =========================================================
# 1. SERVIDOR KEEP-ALIVE
# =========================================================
from http.server import BaseHTTPRequestHandler, HTTPServer

class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Bot activo")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()

    def log_message(self, format, *args):
        return

def iniciar_servidor_web():
    puerto = int(os.environ.get("PORT", 10000))
    servidor = HTTPServer(("0.0.0.0", puerto), KeepAliveHandler)
    print(f"📡 Servidor Keep-Alive en puerto {puerto}")
    servidor.serve_forever()

threading.Thread(target=iniciar_servidor_web, daemon=True).start()

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
os.makedirs(TEMP_DIR, exist_ok=True)

# =========================================================
# 3. CONFIGURACIÓN YT-DLP
# =========================================================
def load_opus_lib():
    if not discord.opus.is_loaded():
        for lib in ['libopus.so.0', 'libopus.so', 'opus']:
            try:
                discord.opus.load_opus(lib)
                print(f"✅ Opus cargado: {lib}")
                return
            except Exception:
                continue
        print("⚠️ No se pudo cargar Opus")

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
    'http_headers': {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        ),
        'Accept-Language': 'en-US,en;q=0.9',
    },
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin',
    'options': '-vn -b:a 192k',
}

EMOJIS_NUMEROS = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '🔟']
EMOJI_CANCELAR = '❌'


def es_error_drm(msg: str) -> bool:
    msg_lower = msg.lower()
    return any(k in msg_lower for k in [
        'drm', 'not available', 'unavailable', 'copyright',
        'geo', 'blocked', 'private', 'removed', 'deleted',
        'not playable', 'preview only', 'snippet', 'go+',
        'subscription', 'monetization',
    ])


def _obtener_mejor_url(info: dict):
    formats = info.get('formats') or []
    if formats:
        audio_formats = [
            f for f in formats
            if f.get('url') and f.get('acodec') and f.get('acodec') != 'none'
        ]
        if audio_formats:
            opus = next((f for f in audio_formats if f.get('acodec') == 'opus'), None)
            if opus and opus.get('url'):
                return opus['url']
            best = max(audio_formats, key=lambda f: (f.get('abr') or f.get('tbr') or 0))
            if best.get('url'):
                return best['url']
    return info.get('url')


def buscar_resultados_sync(query: str, cantidad: int = 15):
    """
    Busca en SoundCloud. Aumentamos a 15 resultados por defecto
    porque muchos suelen estar con DRM.
    """
    search_query = f'scsearch{cantidad}:{query}'
    print(f"🔍 Buscando: {search_query}")
    
    try:
        with yt_dlp.YoutubeDL(YDL_OPTIONS_SC) as ydl:
            info = ydl.extract_info(search_query, download=False)
    except Exception as e:
        raise Exception(f"Error en búsqueda: {e}")
    
    if not info or 'entries' not in info:
        raise Exception("No se encontraron resultados en SoundCloud")
    
    entries = [e for e in (info.get('entries') or []) if e]
    if not entries:
        raise Exception("Búsqueda vacía")
    
    resultados = []
    for entry in entries:
        if not entry:
            continue
        resultados.append({
            'titulo': entry.get('title', 'Sin título'),
            'url': entry.get('webpage_url') or entry.get('url'),
            'duracion': entry.get('duration'),
            'uploader': entry.get('uploader', 'Desconocido'),
            'thumbnail': entry.get('thumbnail'),
        })
    
    print(f"✅ {len(resultados)} resultados encontrados")
    return resultados


def extraer_stream_de_url_sync(url: str):
    """Extrae la URL de streaming. Lanza excepción si es DRM o no disponible."""
    print(f"🎵 Extrayendo stream: {url}")
    with yt_dlp.YoutubeDL(YDL_OPTIONS_SC) as ydl:
        info = ydl.extract_info(url, download=False)
    
    if not info:
        raise Exception("Info vacío")
    
    titulo = info.get('title', 'Desconocido')
    stream_url = _obtener_mejor_url(info)
    
    if not stream_url:
        raise Exception("No se encontró URL de audio")
    
    return stream_url, titulo


def validar_resultados_sync(resultados: list):
    """
    Valida cada resultado para saber si es reproducible o tiene DRM.
    Devuelve la misma lista con un campo extra 'reproducible' (bool) y 'razon'.
    
    Se ejecuta en paralelo usando threads para mayor velocidad.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    def validar_uno(r):
        try:
            with yt_dlp.YoutubeDL({**YDL_OPTIONS_SC, 'socket_timeout': 10}) as ydl:
                info = ydl.extract_info(r['url'], download=False)
            stream_url = _obtener_mejor_url(info)
            if stream_url:
                return {**r, 'reproducible': True, 'razon': '', 'stream_url': stream_url}
            else:
                return {**r, 'reproducible': False, 'razon': 'sin audio', 'stream_url': None}
        except Exception as e:
            msg = str(e)
            razon = 'DRM/Copyright' if es_error_drm(msg) else msg[:60]
            return {**r, 'reproducible': False, 'razon': razon, 'stream_url': None}
    
    # Validar en paralelo con máximo 5 workers para no saturar
    resultados_validados = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(validar_uno, r): r for r in resultados}
        for future in as_completed(futures):
            try:
                resultados_validados.append(future.result())
            except Exception:
                pass
    
    # Reordenar manteniendo el orden original
    orden = {r['url']: i for i, r in enumerate(resultados)}
    resultados_validados.sort(key=lambda r: orden.get(r['url'], 999))
    
    reproducibles = sum(1 for r in resultados_validados if r['reproducible'])
    print(f"✅ Validación completa: {reproducibles}/{len(resultados_validados)} reproducibles")
    
    return resultados_validados


def formatear_duracion(segundos):
    if not segundos:
        return "??:??"
    segundos = int(segundos)
    return f"{segundos // 60}:{segundos % 60:02d}"


# =========================================================
# 4. BOT
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
        intents.reactions = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        load_opus_lib()
        await self.tree.sync()
        print("✅ Bot iniciado")


bot = MusicBot()


# =========================================================
# 5. COMANDO PRINCIPAL: /buscar
# =========================================================
@bot.tree.command(name="buscar", description="Busca y elige con reacciones.")
@app_commands.describe(query="Nombre de la canción a buscar")
async def buscar(interaction: discord.Interaction, query: str):
    await interaction.response.send_message(f"🔍 Buscando **{query}**...")
    
    # 1) Buscar resultados
    try:
        loop = asyncio.get_event_loop()
        resultados = await asyncio.wait_for(
            loop.run_in_executor(None, buscar_resultados_sync, query, 15),
            timeout=60.0
        )
    except asyncio.TimeoutError:
        await interaction.edit_original_response(content="❌ Timeout buscando.")
        return
    except Exception as e:
        await interaction.edit_original_response(content=f"❌ Error: {e}")
        return
    
    if not resultados:
        await interaction.edit_original_response(content="❌ Sin resultados.")
        return
    
    # 2) Validar cuáles son reproducibles (filtrar DRM de antemano)
    await interaction.edit_original_response(
        content=f"🔎 Validando {len(resultados)} resultados, espera..."
    )
    
    try:
        loop = asyncio.get_event_loop()
        resultados = await asyncio.wait_for(
            loop.run_in_executor(None, validar_resultados_sync, resultados),
            timeout=90.0
        )
    except asyncio.TimeoutError:
        await interaction.edit_original_response(
            content="❌ Timeout validando. Prueba de nuevo."
        )
        return
    except Exception as e:
        await interaction.edit_original_response(content=f"❌ Error validando: {e}")
        return
    
    # 3) Filtrar solo los reproducibles y limitar a 10
    reproducibles = [r for r in resultados if r['reproducible']][:10]
    no_reproducibles = [r for r in resultados if not r['reproducible']]
    
    if not reproducibles:
        embed = discord.Embed(
            title="⚠️ Todos los resultados tienen DRM o no están disponibles",
            description=(
                "Ninguno de los resultados pudo validarse como reproducible.\n\n"
                "**Sugerencias:**\n"
                "• Prueba con el nombre exacto de la canción\n"
                "• Añade el artista al nombre\n"
                "• Prueba con `cover`, `remix` o `live` al final\n\n"
                f"**Resultados descartados:** {len(no_reproducibles)}"
            ),
            color=discord.Color.orange()
        )
        # Mostrar los títulos descartados
        titulos_desc = "\n".join(f"• {r['titulo'][:60]} — _{r['razon']}_" 
                                  for r in no_reproducibles[:5])
        if titulos_desc:
            embed.add_field(name="Ejemplos descartados", value=titulos_desc, inline=False)
        
        await interaction.edit_original_response(content=None, embed=embed)
        return
    
    # 4) Construir embed con SOLO los reproducibles
    embed = discord.Embed(
        title=f"🎵 Resultados para: {query}",
        description=(
            f"**{len(reproducibles)} canciones reproducibles** de {len(resultados)} resultados.\n"
            "Reacciona con el número para reproducir.\n"
            "Reacciona con ❌ para cancelar."
        ),
        color=discord.Color.green()
    )
    
    for i, r in enumerate(reproducibles):
        dur = formatear_duracion(r.get('duracion'))
        titulo = r['titulo'][:80]
        uploader = r.get('uploader', 'Desconocido')[:40]
        embed.add_field(
            name=f"{EMOJIS_NUMEROS[i]} {titulo}",
            value=f"⏱️ `{dur}` | 👤 {uploader} | ✅ Reproducible",
            inline=False
        )
    
    embed.set_footer(text="Tienes 60 segundos para elegir")
    
    mensaje = await interaction.edit_original_response(content=None, embed=embed)
    
    # 5) Añadir reacciones (con manejo de errores detallado)
    reacciones_ok = 0
    for i in range(len(reproducibles)):
        try:
            await mensaje.add_reaction(EMOJIS_NUMEROS[i])
            reacciones_ok += 1
        except discord.Forbidden:
            await interaction.edit_original_response(
                content=(
                    "❌ **El bot no tiene permiso para añadir reacciones.**\n\n"
                    "**Solución:** En la configuración del canal, dale al bot "
                    "el permiso `Add Reactions` (Añadir reacciones) y "
                    "`Read Message History` (Leer historial de mensajes).\n\n"
                    "**Alternativa:** Usa `/play <query>` que reproduce "
                    "el primer resultado automáticamente."
                )
            )
            return
        except Exception as e:
            print(f"⚠️ Error añadiendo reacción {i}: {e}")
            continue
    
    try:
        await mensaje.add_reaction(EMOJI_CANCELAR)
    except Exception as e:
        print(f"⚠️ Error añadiendo cancelar: {e}")
    
    if reacciones_ok == 0:
        return
    
    print(f"✅ {reacciones_ok} reacciones añadidas correctamente")
    
    # 6) Esperar reacción del usuario
    def check_reaccion(reaction, user):
        return (
            user.id == interaction.user.id
            and reaction.message.id == mensaje.id
            and (
                str(reaction.emoji) in EMOJIS_NUMEROS[:len(reproducibles)]
                or str(reaction.emoji) == EMOJI_CANCELAR
            )
        )
    
    try:
        reaction, user = await bot.wait_for('reaction_add', timeout=60.0, check=check_reaccion)
    except asyncio.TimeoutError:
        try:
            await mensaje.clear_reactions()
        except Exception:
            pass
        await interaction.edit_original_response(
            content="⏰ Tiempo agotado. Vuelve a usar `/buscar`.",
            embed=None
        )
        return
    
    emoji_elegido = str(reaction.emoji)
    
    try:
        await mensaje.clear_reactions()
    except Exception:
        pass
    
    if emoji_elegido == EMOJI_CANCELAR:
        await interaction.edit_original_response(content="❌ Cancelado.", embed=None)
        return
    
    idx = EMOJIS_NUMEROS.index(emoji_elegido)
    elegido = reproducibles[idx]
    
    await interaction.edit_original_response(
        content=f"⏳ Reproduciendo: **{elegido['titulo']}**...",
        embed=None
    )
    
    # 7) Conectar al canal de voz
    if not interaction.guild.voice_client:
        if interaction.user.voice:
            try:
                await interaction.user.voice.channel.connect(cls=voice_recv.VoiceRecvClient)
            except Exception as e:
                await interaction.edit_original_response(content=f"❌ No pude conectarme: {e}")
                return
        else:
            await interaction.edit_original_response(content="❌ ¡Debes estar en un canal de voz!")
            return
    
    vc = interaction.guild.voice_client
    
    # 8) Reproducir usando el stream_url ya validado
    stream_url = elegido.get('stream_url')
    if not stream_url:
        # Reintentar extracción
        try:
            loop = asyncio.get_event_loop()
            stream_url, _ = await asyncio.wait_for(
                loop.run_in_executor(None, extraer_stream_de_url_sync, elegido['url']),
                timeout=30.0
            )
        except Exception as e:
            await interaction.edit_original_response(
                content=f"❌ Error al extraer: {e}\nPrueba con otra opción."
            )
            return
    
    def after_playing(error):
        if error:
            print(f"⚠️ Error en reproducción: {error}")
    
    try:
        if vc.is_playing():
            vc.stop()
        
        source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)
        vc.play(source, after=after_playing)
        await interaction.edit_original_response(
            content=f"🎵 Reproduciendo: **{elegido['titulo']}**"
        )
    except Exception as e:
        await interaction.edit_original_response(content=f"❌ Error: {e}")


# =========================================================
# 6. COMANDO /play (modo rápido)
# =========================================================
@bot.tree.command(name="play", description="Reproduce el primer resultado reproducible.")
@app_commands.describe(query="Nombre de la canción")
async def play(interaction: discord.Interaction, query: str):
    await interaction.response.send_message(f"⏳ Buscando **{query}**...")
    
    try:
        loop = asyncio.get_event_loop()
        resultados = await asyncio.wait_for(
            loop.run_in_executor(None, buscar_resultados_sync, query, 15),
            timeout=60.0
        )
    except Exception as e:
        await interaction.edit_original_response(content=f"❌ Error: {e}")
        return
    
    await interaction.edit_original_response(content="🔎 Validando resultados...")
    
    try:
        loop = asyncio.get_event_loop()
        resultados = await asyncio.wait_for(
            loop.run_in_executor(None, validar_resultados_sync, resultados),
            timeout=90.0
        )
    except Exception as e:
        await interaction.edit_original_response(content=f"❌ Error: {e}")
        return
    
    reproducibles = [r for r in resultados if r['reproducible']]
    if not reproducibles:
        await interaction.edit_original_response(
            content="❌ Ningún resultado reproducible. Prueba con otro nombre."
        )
        return
    
    elegido = reproducibles[0]
    
    # Conectar
    if not interaction.guild.voice_client:
        if interaction.user.voice:
            try:
                await interaction.user.voice.channel.connect(cls=voice_recv.VoiceRecvClient)
            except Exception as e:
                await interaction.edit_original_response(content=f"❌ No pude conectarme: {e}")
                return
        else:
            await interaction.edit_original_response(content="❌ ¡Debes estar en un canal de voz!")
            return
    
    vc = interaction.guild.voice_client
    
    def after_playing(error):
        if error:
            print(f"⚠️ Error: {error}")
    
    try:
        if vc.is_playing():
            vc.stop()
        source = discord.FFmpegPCMAudio(elegido['stream_url'], **FFMPEG_OPTIONS)
        vc.play(source, after=after_playing)
        await interaction.edit_original_response(
            content=f"🎵 Reproduciendo: **{elegido['titulo']}**"
        )
    except Exception as e:
        await interaction.edit_original_response(content=f"❌ Error: {e}")


# =========================================================
# 7. OTROS COMANDOS
# =========================================================
@bot.tree.command(name="join", description="Une al bot a tu canal de voz.")
async def join(interaction: discord.Interaction):
    if not interaction.user.voice:
        await interaction.response.send_message("❌ ¡Debes estar en un canal!", ephemeral=True)
        return
    channel = interaction.user.voice.channel
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.move_to(channel)
    else:
        await channel.connect(cls=voice_recv.VoiceRecvClient)
    await interaction.response.send_message(f"✅ Me uní a **{channel.name}**")


@bot.tree.command(name="background", description="Escucha el canal en segundo plano.")
async def background(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if not vc:
        await interaction.response.send_message("❌ No estoy en un canal.", ephemeral=True)
        return
    try:
        vc.listen(VoiceActivitySink())
        await interaction.response.send_message("🎙️ Modo escucha activado.")
    except Exception as e:
        await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)


@bot.tree.command(name="leave", description="Desconecta al bot.")
async def leave(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc:
        await vc.disconnect()
        await interaction.response.send_message("👋 Desconectado.")
    else:
        await interaction.response.send_message("❌ No estoy en un canal.", ephemeral=True)


# =========================================================
# 8. EJECUCIÓN
# =========================================================
if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("❌ ERROR: DISCORD_TOKEN no configurado")
        exit(1)
    bot.run(token)
