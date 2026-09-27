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


YDL_OPTIONS_BUSQUEDA = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': True,   # ← Saltar DRM automáticamente
    'quiet': True,
    'no_warnings': True,
    'source_address': '0.0.0.0',
    'socket_timeout': 12,
    'retries': 2,
    'extractor_retries': 2,
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

YDL_OPTIONS_TRACK = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'quiet': True,
    'no_warnings': True,
    'source_address': '0.0.0.0',
    'socket_timeout': 15,
    'retries': 2,
    'extractor_retries': 2,
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


def _formatear_duracion(segundos):
    if not segundos:
        return "??:??"
    segundos = int(segundos)
    return f"{segundos // 60}:{segundos % 60:02d}"


def buscar_resultados_sync(query: str):
    """Busca en SoundCloud con 3 estrategias para maximizar resultados."""
    todas_queries = [
        f'scsearch15:{query}',
        f'scsearch5:{query} cover',
        f'scsearch5:{query} remix',
    ]
    
    resultados = []
    urls_vistas = set()
    
    for q in todas_queries:
        print(f"🔍 Buscando: {q}")
        try:
            with yt_dlp.YoutubeDL(YDL_OPTIONS_BUSQUEDA) as ydl:
                info = ydl.extract_info(q, download=False)
        except Exception as e:
            print(f"⚠️ Error en '{q}': {str(e)[:100]}")
            continue
        
        if not info:
            continue
        
        entries = info.get('entries') or []
        for entry in entries:
            if not entry:
                continue
            
            url = entry.get('webpage_url') or entry.get('url')
            if not url or url in urls_vistas:
                continue
            
            if not entry.get('formats') and not entry.get('url'):
                continue
            
            urls_vistas.add(url)
            resultados.append({
                'titulo': entry.get('title', 'Sin título'),
                'url': url,
                'duracion': entry.get('duration'),
                'uploader': entry.get('uploader', 'Desconocido'),
            })
            
            if len(resultados) >= 20:
                break
        
        if len(resultados) >= 20:
            break
    
    print(f"✅ {len(resultados)} resultados reproducibles")
    return resultados


def extraer_stream_de_url_sync(url: str):
    """Extrae la URL de streaming de un track específico."""
    print(f"🎵 Extrayendo: {url[:80]}")
    with yt_dlp.YoutubeDL(YDL_OPTIONS_TRACK) as ydl:
        info = ydl.extract_info(url, download=False)
    
    if not info:
        raise Exception("Info vacío")
    
    titulo = info.get('title', 'Desconocido')
    stream_url = _obtener_mejor_url(info)
    
    if not stream_url:
        raise Exception("No se encontró URL de audio")
    
    return stream_url, titulo


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
        intents.message_content = True  # ← Necesario para leer números en el chat
        intents.voice_states = True
        intents.reactions = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        load_opus_lib()
        await self.tree.sync()
        print("✅ Bot iniciado")


bot = MusicBot()


# =========================================================
# 5. FUNCIÓN AUXILIAR: Espera selección por reacción O por chat
# =========================================================
async def esperar_seleccion(interaction, mensaje, cantidad_resultados, timeout=60.0):
    """
    Espera a que el usuario elija UNA de dos formas:
    1. Reaccionando con un emoji numérico (1️⃣-🔟) o ❌
    2. Escribiendo el número (1-10) o 'cancelar' en el chat
    
    Devuelve: (indice_seleccionado, forma) donde forma es 'reaccion', 'chat' o 'cancelar'
    Devuelve (None, 'timeout') si se agota el tiempo.
    """
    loop = asyncio.get_event_loop()
    
    # Future que se resolverá con la primera respuesta
    futuro_resultado = loop.create_future()
    
    def resolver(indice, forma):
        if not futuro_resultado.done():
            futuro_resultado.set_result((indice, forma))
    
    # --- Listener de reacciones ---
    def check_reaccion(reaction, user):
        return (
            user.id == interaction.user.id
            and reaction.message.id == mensaje.id
            and (
                str(reaction.emoji) in EMOJIS_NUMEROS[:cantidad_resultados]
                or str(reaction.emoji) == EMOJI_CANCELAR
            )
        )
    
    async def escuchar_reacciones():
        try:
            reaction, user = await bot.wait_for(
                'reaction_add',
                timeout=timeout,
                check=check_reaccion
            )
            emoji = str(reaction.emoji)
            if emoji == EMOJI_CANCELAR:
                resolver(-1, 'cancelar')
            else:
                idx = EMOJIS_NUMEROS.index(emoji)
                resolver(idx, 'reaccion')
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            print(f"⚠️ Error escuchando reacciones: {e}")
    
    # --- Listener de mensajes en el chat ---
    def check_mensaje(message):
        # Solo mensajes del mismo usuario, en el mismo canal
        if message.author.id != interaction.user.id:
            return False
        if message.channel.id != interaction.channel_id:
            return False
        
        contenido = message.content.strip().lower()
        
        # Cancelar
        if contenido in ('cancelar', 'cancela', 'cancel', 'x', 'no'):
            return True
        
        # Número del 1 al N
        if contenido.isdigit():
            num = int(contenido)
            if 1 <= num <= cantidad_resultados:
                return True
        
        return False
    
    async def escuchar_mensajes():
        try:
            message = await bot.wait_for(
                'message',
                timeout=timeout,
                check=check_mensaje
            )
            contenido = message.content.strip().lower()
            
            if contenido in ('cancelar', 'cancela', 'cancel', 'x', 'no'):
                resolver(-1, 'cancelar')
            else:
                idx = int(contenido) - 1  # Usuario escribe 1-10, índice es 0-9
                resolver(idx, 'chat')
            
            # Borrar el mensaje del usuario para mantener limpio el canal
            try:
                await message.delete()
            except Exception:
                pass
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            print(f"⚠️ Error escuchando mensajes: {e}")
    
    # Lanzar ambos listeners en paralelo
    tarea_reacciones = asyncio.create_task(escuchar_reacciones())
    tarea_mensajes = asyncio.create_task(escuchar_mensajes())
    
    try:
        resultado = await asyncio.wait_for(futuro_resultado, timeout=timeout + 1)
    except asyncio.TimeoutError:
        resultado = (None, 'timeout')
    finally:
        # Cancelar las tareas pendientes
        for t in (tarea_reacciones, tarea_mensajes):
            if not t.done():
                t.cancel()
        
        # Esperar a que terminen (con manejo de cancelación)
        for t in (tarea_reacciones, tarea_mensajes):
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
    
    return resultado


# =========================================================
# 6. COMANDO /buscar
# =========================================================
@bot.tree.command(name="buscar", description="Busca y elige con reacciones o escribiendo el número.")
@app_commands.describe(query="Nombre de la canción a buscar")
async def buscar(interaction: discord.Interaction, query: str):
    await interaction.response.send_message(f"🔍 Buscando **{query}**...")
    
    # Buscar resultados
    try:
        loop = asyncio.get_event_loop()
        resultados = await asyncio.wait_for(
            loop.run_in_executor(None, buscar_resultados_sync, query),
            timeout=60.0
        )
    except asyncio.TimeoutError:
        await interaction.edit_original_response(content="❌ Timeout buscando.")
        return
    except Exception as e:
        await interaction.edit_original_response(content=f"❌ Error: {str(e)[:300]}")
        return
    
    if not resultados:
        await interaction.edit_original_response(
            content=(
                f"❌ **No hay resultados reproducibles para:** `{query}`\n\n"
                f"**Sugerencias:**\n"
                f"• `{query} cover`\n"
                f"• `{query} remix`\n"
                f"• `{query} instrumental`"
            )
        )
        return
    
    resultados = resultados[:10]
    
    # Construir embed
    embed = discord.Embed(
        title=f"🎵 Resultados para: {query}",
        description=(
            f"**{len(resultados)} canciones disponibles**\n\n"
            "**Elige de 2 formas:**\n"
            "• 🎯 **Reacciona** con el emoji numérico (1️⃣-🔟)\n"
            "• 💬 **Escribe** el número en el chat (ej: `3`)\n\n"
            "Para cancelar: reacciona con ❌ o escribe `cancelar`"
        ),
        color=discord.Color.green()
    )
    
    for i, r in enumerate(resultados):
        dur = _formatear_duracion(r.get('duracion'))
        titulo = r['titulo'][:80]
        uploader = r.get('uploader', 'Desconocido')[:40]
        embed.add_field(
            name=f"**{i+1}.** {titulo}",
            value=f"⏱️ `{dur}` | 👤 {uploader}",
            inline=False
        )
    
    embed.set_footer(text="Tienes 60 segundos para elegir (reacción o chat)")
    
    mensaje = await interaction.edit_original_response(content=None, embed=embed)
    
    # Añadir reacciones
    try:
        for i in range(len(resultados)):
            await mensaje.add_reaction(EMOJIS_NUMEROS[i])
        await mensaje.add_reaction(EMOJI_CANCELAR)
    except discord.Forbidden:
        # Si no puede reaccionar, avisa pero permite modo chat
        await interaction.edit_original_response(
            content=(
                "⚠️ **El bot no puede reaccionar**, pero aún puedes escribir el número.\n\n"
                f"**Escribe el número (1-{len(resultados)}) en el chat o `cancelar`.**"
            ),
            embed=embed
        )
    except Exception as e:
        print(f"⚠️ Error añadiendo reacciones: {e}")
    
    # Esperar selección (reacción o chat)
    idx, forma = await esperar_seleccion(
        interaction, mensaje, len(resultados), timeout=60.0
    )
    
    # Limpiar reacciones
    try:
        await mensaje.clear_reactions()
    except Exception:
        pass
    
    # Manejar timeout
    if forma == 'timeout' or idx is None:
        await interaction.edit_original_response(
            content="⏰ Tiempo agotado. Vuelve a usar `/buscar`.",
            embed=None
        )
        return
    
    # Manejar cancelación
    if forma == 'cancelar' or idx == -1:
        await interaction.edit_original_response(content="❌ Cancelado.", embed=None)
        return
    
    elegido = resultados[idx]
    
    forma_texto = "reacción" if forma == 'reaccion' else "chat"
    await interaction.edit_original_response(
        content=f"⏳ Cargando **{elegido['titulo']}** (elegido por {forma_texto})...",
        embed=None
    )
    
    # Conectar al canal de voz
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
    
    # Fallback: probar el elegido y luego los demás
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
                timeout=20.0
            )
            reproduciendo_idx = intento_idx
            break
        except Exception as e:
            print(f"⚠️ Fallo '{candidato['titulo'][:50]}': {str(e)[:80]}")
            continue
    
    if not stream_url:
        await interaction.edit_original_response(
            content=(
                "❌ **Ninguna canción se pudo reproducir.**\n"
                "Prueba: `/buscar <nombre> cover`"
            )
        )
        return
    
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
                    f"_(la elegida tenía DRM, usé otra)_"
                )
            )
        else:
            await interaction.edit_original_response(
                content=f"🎵 Reproduciendo: **{titulo_final}**"
            )
    except Exception as e:
        await interaction.edit_original_response(content=f"❌ Error: {e}")


# =========================================================
# 7. COMANDO /play
# =========================================================
@bot.tree.command(name="play", description="Reproduce el primer resultado disponible.")
@app_commands.describe(query="Nombre de la canción")
async def play(interaction: discord.Interaction, query: str):
    await interaction.response.send_message(f"⏳ Buscando **{query}**...")
    
    try:
        loop = asyncio.get_event_loop()
        resultados = await asyncio.wait_for(
            loop.run_in_executor(None, buscar_resultados_sync, query),
            timeout=60.0
        )
    except Exception as e:
        await interaction.edit_original_response(content=f"❌ Error: {str(e)[:300]}")
        return
    
    if not resultados:
        await interaction.edit_original_response(
            content=f"❌ Sin resultados. Prueba: `/buscar {query} cover`"
        )
        return
    
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
    
    for i, r in enumerate(resultados):
        try:
            await interaction.edit_original_response(
                content=f"⏳ Probando {i+1}/{len(resultados)}: **{r['titulo'][:60]}**..."
            )
            loop = asyncio.get_event_loop()
            stream_url, titulo = await asyncio.wait_for(
                loop.run_in_executor(None, extraer_stream_de_url_sync, r['url']),
                timeout=20.0
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
            print(f"⚠️ Fallo {i+1}: {str(e)[:80]}")
            continue
    
    await interaction.edit_original_response(
        content=f"❌ Ningún resultado reproducible. Prueba: `/buscar {query} cover`"
    )


# =========================================================
# 8. OTROS COMANDOS
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
# 9. EJECUCIÓN
# =========================================================
if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("❌ ERROR: DISCORD_TOKEN no configurado")
        exit(1)
    bot.run(token)
