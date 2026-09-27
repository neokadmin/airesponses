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
    'socket_timeout': 15,
    'retries': 3,
    'extractor_retries': 3,
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


def buscar_resultados_sync(query: str, cantidad: int = 10):
    """
    Busca en SoundCloud. Ahora devuelve resultados RÁPIDO.
    NO valida DRM aquí (eso se hace al reproducir).
    """
    search_query = f'scsearch{cantidad}:{query}'
    print(f"🔍 Buscando: {search_query}")
    
    with yt_dlp.YoutubeDL(YDL_OPTIONS_SC) as ydl:
        info = ydl.extract_info(search_query, download=False)
    
    if not info or 'entries' not in info:
        raise Exception("No se encontraron resultados")
    
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
        })
    
    print(f"✅ {len(resultados)} resultados encontrados")
    return resultados


def extraer_stream_de_url_sync(url: str):
    """Extrae la URL de streaming. Lanza excepción si es DRM."""
    print(f"🎵 Extrayendo: {url}")
    with yt_dlp.YoutubeDL(YDL_OPTIONS_SC) as ydl:
        info = ydl.extract_info(url, download=False)
    
    if not info:
        raise Exception("Info vacío")
    
    titulo = info.get('title', 'Desconocido')
    stream_url = _obtener_mejor_url(info)
    
    if not stream_url:
        raise Exception("No se encontró URL de audio")
    
    return stream_url, titulo


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
# 5. COMANDO /buscar (VERSIÓN ARREGLADA - RÁPIDA)
# =========================================================
@bot.tree.command(name="buscar", description="Busca y elige con reacciones.")
@app_commands.describe(query="Nombre de la canción a buscar")
async def buscar(interaction: discord.Interaction, query: str):
    # Responder INMEDIATAMENTE para que no parezca colgado
    await interaction.response.send_message(f"🔍 Buscando **{query}** en SoundCloud...")
    
    # === PASO 1: Buscar resultados (rápido, ~5 seg) ===
    try:
        loop = asyncio.get_event_loop()
        resultados = await asyncio.wait_for(
            loop.run_in_executor(None, buscar_resultados_sync, query, 10),
            timeout=45.0
        )
    except asyncio.TimeoutError:
        await interaction.edit_original_response(
            content="❌ Timeout buscando. Prueba de nuevo."
        )
        return
    except Exception as e:
        await interaction.edit_original_response(
            content=f"❌ Error buscando: {e}"
        )
        return
    
    if not resultados:
        await interaction.edit_original_response(
            content="❌ No se encontraron resultados."
        )
        return
    
    # Limitar a 10 (por los emojis)
    resultados = resultados[:10]
    
    # === PASO 2: Mostrar el menú INMEDIATAMENTE ===
    embed = discord.Embed(
        title=f"🎵 Resultados para: {query}",
        description=(
            "Reacciona con el número para reproducir esa canción.\n"
            "Reacciona con ❌ para cancelar.\n\n"
            "⚠️ Si la canción elegida tiene DRM, te lo avisaré y podrás elegir otra."
        ),
        color=discord.Color.blurple()
    )
    
    for i, r in enumerate(resultados):
        dur = formatear_duracion(r.get('duracion'))
        titulo = r['titulo'][:80]
        uploader = r.get('uploader', 'Desconocido')[:40]
        embed.add_field(
            name=f"{EMOJIS_NUMEROS[i]} {titulo}",
            value=f"⏱️ `{dur}` | 👤 {uploader}",
            inline=False
        )
    
    embed.set_footer(text="Tienes 60 segundos para elegir")
    
    mensaje = await interaction.edit_original_response(content=None, embed=embed)
    
    # === PASO 3: Añadir reacciones ===
    try:
        for i in range(len(resultados)):
            await mensaje.add_reaction(EMOJIS_NUMEROS[i])
        await mensaje.add_reaction(EMOJI_CANCELAR)
        print(f"✅ Reacciones añadidas correctamente")
    except discord.Forbidden:
        await interaction.edit_original_response(
            content=(
                "❌ **El bot no puede añadir reacciones.**\n\n"
                "**Solución:** Dale al bot el permiso `Add Reactions` en este canal.\n\n"
                "**Alternativa rápida:** Usa `/play` que reproduce automáticamente."
            ),
            embed=None
        )
        return
    except Exception as e:
        print(f"⚠️ Error añadiendo reacciones: {e}")
        await interaction.edit_original_response(
            content=f"❌ Error añadiendo reacciones: {e}",
            embed=None
        )
        return
    
    # === PASO 4: Esperar reacción ===
    def check_reaccion(reaction, user):
        return (
            user.id == interaction.user.id
            and reaction.message.id == mensaje.id
            and (
                str(reaction.emoji) in EMOJIS_NUMEROS[:len(resultados)]
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
    elegido = resultados[idx]
    
    # === PASO 5: Ahora SÍ validamos el elegido ===
    await interaction.edit_original_response(
        content=f"⏳ Cargando **{elegido['titulo']}**...",
        embed=None
    )
    
    # Conectar al canal de voz
    if not interaction.guild.voice_client:
        if interaction.user.voice:
            try:
                await interaction.user.voice.channel.connect(cls=voice_recv.VoiceRecvClient)
            except Exception as e:
                await interaction.edit_original_response(
                    content=f"❌ No pude conectarme: {e}"
                )
                return
        else:
            await interaction.edit_original_response(
                content="❌ ¡Debes estar en un canal de voz!"
            )
            return
    
    vc = interaction.guild.voice_client
    
    # === PASO 6: Probar el elegido + fallback a otros ===
    # Si el elegido falla (DRM), probamos los siguientes automáticamente
    orden_prueba = [idx] + [i for i in range(len(resultados)) if i != idx]
    
    stream_url = None
    titulo_final = None
    reproduciendo_idx = None
    
    for intento_idx in orden_prueba:
        candidato = resultados[intento_idx]
        try:
            loop = asyncio.get_event_loop()
            stream_url, titulo_final = await asyncio.wait_for(
                loop.run_in_executor(None, extraer_stream_de_url_sync, candidato['url']),
                timeout=25.0
            )
            reproduciendo_idx = intento_idx
            break  # ¡Éxito!
        except asyncio.TimeoutError:
            print(f"⚠️ Timeout con: {candidato['titulo']}")
            continue
        except Exception as e:
            msg = str(e)
            if es_error_drm(msg):
                print(f"⚠️ DRM detectado en: {candidato['titulo']}")
            else:
                print(f"⚠️ Error con {candidato['titulo']}: {msg[:80]}")
            continue
    
    if not stream_url:
        await interaction.edit_original_response(
            content=(
                "❌ **Ninguna de las canciones se pudo reproducir.**\n"
                "Todas tienen DRM o están bloqueadas.\n\n"
                "**Sugerencia:** Prueba `/buscar` añadiendo `cover`, `remix` o `live` al final."
            )
        )
        return
    
    # === PASO 7: Reproducir ===
    def after_playing(error):
        if error:
            print(f"⚠️ Error reproduciendo: {error}")
    
    try:
        if vc.is_playing():
            vc.stop()
        
        source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)
        vc.play(source, after=after_playing)
        
        if reproduciendo_idx != idx:
            await interaction.edit_original_response(
                content=(
                    f"🎵 Reproduciendo: **{titulo_final}**\n"
                    f"_(la original tenía DRM, cambié a otro resultado)_"
                )
            )
        else:
            await interaction.edit_original_response(
                content=f"🎵 Reproduciendo: **{titulo_final}**"
            )
    except Exception as e:
        await interaction.edit_original_response(
            content=f"❌ Error al reproducir: {e}"
        )


# =========================================================
# 6. COMANDO /play
# =========================================================
@bot.tree.command(name="play", description="Reproduce el primer resultado disponible.")
@app_commands.describe(query="Nombre de la canción")
async def play(interaction: discord.Interaction, query: str):
    await interaction.response.send_message(f"⏳ Buscando **{query}**...")
    
    try:
        loop = asyncio.get_event_loop()
        resultados = await asyncio.wait_for(
            loop.run_in_executor(None, buscar_resultados_sync, query, 10),
            timeout=45.0
        )
    except Exception as e:
        await interaction.edit_original_response(content=f"❌ Error: {e}")
        return
    
    if not resultados:
        await interaction.edit_original_response(content="❌ Sin resultados.")
        return
    
    # Conectar al canal
    if not interaction.guild.voice_client:
        if interaction.user.voice:
            try:
                await interaction.user.voice.channel.connect(cls=voice_recv.VoiceRecvClient)
            except Exception as e:
                await interaction.edit_original_response(content=f"❌ No pude conectarme: {e}")
                return
        else:
            await interaction.edit_original_response(content="❌ ¡Debes estar en un canal!")
            return
    
    vc = interaction.guild.voice_client
    
    # Probar uno por uno hasta encontrar reproducible
    for i, r in enumerate(resultados):
        try:
            await interaction.edit_original_response(
                content=f"⏳ Probando resultado {i+1}/{len(resultados)}: **{r['titulo'][:60]}**..."
            )
            
            loop = asyncio.get_event_loop()
            stream_url, titulo = await asyncio.wait_for(
                loop.run_in_executor(None, extraer_stream_de_url_sync, r['url']),
                timeout=25.0
            )
            
            def after_playing(error):
                if error:
                    print(f"⚠️ Error: {error}")
            
            if vc.is_playing():
                vc.stop()
            
            source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)
            vc.play(source, after=after_playing)
            
            await interaction.edit_original_response(
                content=f"🎵 Reproduciendo: **{titulo}**"
            )
            return
            
        except Exception as e:
            msg = str(e)
            if es_error_drm(msg):
                print(f"⚠️ DRM en: {r['titulo']}")
            continue
    
    await interaction.edit_original_response(
        content="❌ Ningún resultado reproducible. Prueba con otro nombre."
    )


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
