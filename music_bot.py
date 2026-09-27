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
    'ignoreerrors': True,
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


PALABRAS_REMIX = [
    'remix', 'cover', 'instrumental', 'karaoke', 'slowed',
    'reverb', 'sped up', 'speed up', 'nightcore', 'mashup',
    'bootleg', 'flip', 'edit', 'version', 'mix', 'dj ',
    'rework', 'refix', 'vip', 'extended', 'radio edit',
    'acoustic', 'live', 'demo', 'teaser', 'snippet', 'preview',
]


def _clasificar_resultado(titulo: str, query: str) -> str:
    titulo_lower = titulo.lower()
    if 'remix' in titulo_lower or 'flip' in titulo_lower or 'edit' in titulo_lower:
        return 'REMIX'
    if 'cover' in titulo_lower:
        return 'COVER'
    if 'instrumental' in titulo_lower or 'karaoke' in titulo_lower:
        return 'INSTRUMENTAL'
    if 'slowed' in titulo_lower or 'reverb' in titulo_lower:
        return 'SLOWED'
    if 'sped up' in titulo_lower or 'speed up' in titulo_lower or 'nightcore' in titulo_lower:
        return 'SPED UP'
    if 'live' in titulo_lower:
        return 'LIVE'
    if 'mashup' in titulo_lower:
        return 'MASHUP'
    return 'ORIGINAL'


def buscar_resultados_sync(query: str):
    print(f"🔍 Buscando ORIGINAL: {query}")
    
    resultados = []
    urls_vistas = set()
    
    try:
        with yt_dlp.YoutubeDL(YDL_OPTIONS_BUSQUEDA) as ydl:
            info = ydl.extract_info(f'scsearch20:{query}', download=False)
    except Exception as e:
        print(f"⚠️ Error buscando original: {str(e)[:100]}")
        info = None
    
    originales = []
    no_originales = []
    
    if info:
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
            titulo = entry.get('title', 'Sin título')
            categoria = _clasificar_resultado(titulo, query)
            
            item = {
                'titulo': titulo,
                'url': url,
                'duracion': entry.get('duration'),
                'uploader': entry.get('uploader', 'Desconocido'),
                'categoria': categoria,
            }
            
            if categoria == 'ORIGINAL':
                originales.append(item)
            else:
                no_originales.append(item)
    
    print(f"   ✅ {len(originales)} originales, {len(no_originales)} no-originales")
    
    if len(originales) >= 3:
        return originales[:10]
    
    resultados = originales.copy()
    for item in no_originales:
        if len(resultados) >= 10:
            break
        resultados.append(item)
    
    if not resultados:
        for extra in ['cover', 'remix']:
            try:
                with yt_dlp.YoutubeDL(YDL_OPTIONS_BUSQUEDA) as ydl:
                    info = ydl.extract_info(f'scsearch5:{query} {extra}', download=False)
                if info:
                    for entry in (info.get('entries') or []):
                        if not entry:
                            continue
                        url = entry.get('webpage_url') or entry.get('url')
                        if not url or url in urls_vistas:
                            continue
                        urls_vistas.add(url)
                        titulo = entry.get('title', 'Sin título')
                        resultados.append({
                            'titulo': titulo,
                            'url': url,
                            'duracion': entry.get('duration'),
                            'uploader': entry.get('uploader', 'Desconocido'),
                            'categoria': _clasificar_resultado(titulo, query),
                        })
                        if len(resultados) >= 10:
                            break
            except Exception as e:
                print(f"⚠️ Error con '{extra}': {str(e)[:80]}")
            if len(resultados) >= 10:
                break
    
    return resultados[:10]


def extraer_stream_de_url_sync(url: str):
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
        intents.message_content = True
        intents.voice_states = True
        intents.reactions = True
        intents.guilds = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        load_opus_lib()
        await self.tree.sync()
        print("=" * 60)
        print("✅ Bot iniciado y comandos sincronizados")
        print(f"   intents.message_content = {self.intents.message_content}")
        print(f"   intents.reactions = {self.intents.reactions}")
        print(f"   intents.voice_states = {self.intents.voice_states}")
        print("=" * 60)


bot = MusicBot()


# =========================================================
# 5. ESPERAR SELECCIÓN (reacción o chat) — VERSIÓN ROBUSTA
# =========================================================
async def esperar_seleccion(interaction, mensaje, cantidad_resultados, timeout=90.0):
    """
    Espera selección por reacción O por chat.
    Hace LOG de todo para diagnosticar.
    """
    loop = asyncio.get_event_loop()
    futuro_resultado = loop.create_future()
    evento_cancelar_reacciones = asyncio.Event()
    
    print(f"⏳ Esperando selección del usuario {interaction.user} "
          f"({cantidad_resultados} opciones, {timeout}s)")
    
    def resolver(indice, forma):
        if not futuro_resultado.done():
            print(f"   🎯 Resuelto: idx={indice}, forma={forma}")
            futuro_resultado.set_result((indice, forma))
    
    # Listener de reacciones
    def check_reaccion(reaction, user):
        mismo_mensaje = reaction.message.id == mensaje.id
        mismo_usuario = user.id == interaction.user.id
        es_bot = user.bot
        
        if mismo_mensaje and mismo_usuario and not es_bot:
            print(f"   🔔 Reacción detectada: {reaction.emoji} de {user}")
        
        return (
            mismo_usuario
            and not es_bot
            and mismo_mensaje
            and (
                str(reaction.emoji) in EMOJIS_NUMEROS[:cantidad_resultados]
                or str(reaction.emoji) == EMOJI_CANCELAR
            )
        )
    
    async def escuchar_reacciones():
        try:
            reaction, user = await bot.wait_for(
                'reaction_add', timeout=timeout, check=check_reaccion
            )
            emoji = str(reaction.emoji)
            if emoji == EMOJI_CANCELAR:
                resolver(-1, 'cancelar')
            else:
                resolver(EMOJIS_NUMEROS.index(emoji), 'reaccion')
        except asyncio.TimeoutError:
            print("   ⏰ Listener de reacciones: timeout")
        except asyncio.CancelledError:
            print("   ❌ Listener de reacciones: cancelado")
        except Exception as e:
            print(f"   ⚠️ Error en listener de reacciones: {e}")
    
    # Listener de mensajes
    def check_mensaje(message):
        if message.author.id != interaction.user.id:
            return False
        if message.channel.id != interaction.channel_id:
            return False
        if message.author.bot:
            return False
        contenido = message.content.strip().lower()
        if contenido in ('cancelar', 'cancela', 'cancel', 'x', 'no'):
            return True
        if contenido.isdigit():
            num = int(contenido)
            if 1 <= num <= cantidad_resultados:
                return True
        return False
    
    async def escuchar_mensajes():
        try:
            message = await bot.wait_for('message', timeout=timeout, check=check_mensaje)
            contenido = message.content.strip().lower()
            print(f"   💬 Mensaje detectado: '{contenido}'")
            if contenido in ('cancelar', 'cancela', 'cancel', 'x', 'no'):
                resolver(-1, 'cancelar')
            else:
                resolver(int(contenido) - 1, 'chat')
            try:
                await message.delete()
            except Exception:
                pass
        except asyncio.TimeoutError:
            print("   ⏰ Listener de mensajes: timeout")
        except asyncio.CancelledError:
            print("   ❌ Listener de mensajes: cancelado")
        except Exception as e:
            print(f"   ⚠️ Error en listener de mensajes: {e}")
    
    tarea_reacciones = asyncio.create_task(escuchar_reacciones())
    tarea_mensajes = asyncio.create_task(escuchar_mensajes())
    
    try:
        resultado = await asyncio.wait_for(futuro_resultado, timeout=timeout + 2)
    except asyncio.TimeoutError:
        print("   ⏰ Timeout total esperando selección")
        resultado = (None, 'timeout')
    finally:
        for t in (tarea_reacciones, tarea_mensajes):
            if not t.done():
                t.cancel()
        for t in (tarea_reacciones, tarea_mensajes):
            try:
                await t
            except Exception:
                pass
    
    return resultado


# =========================================================
# 6. VERIFICAR PERMISOS ANTES DE MOSTRAR MENÚ
# =========================================================
async def verificar_permisos_canal(interaction):
    """
    Verifica que el bot tenga los permisos necesarios en el canal.
    Devuelve (ok: bool, mensaje_error: str|None)
    """
    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel):
        return True, None
    
    me = interaction.guild.me
    
    # Permisos requeridos
    permisos_req = {
        'add_reactions': 'Añadir reacciones',
        'read_message_history': 'Leer historial de mensajes',
        'send_messages': 'Enviar mensajes',
    }
    
    if not isinstance(channel, discord.Thread):
        permisos = channel.permissions_for(me)
    else:
        permisos = channel.permissions_for(me)
    
    faltantes = []
    for perm_key, nombre in permisos_req.items():
        if not getattr(permisos, perm_key, False):
            faltantes.append(nombre)
    
    if faltantes:
        msg = (
            f"⚠️ **Faltan permisos del bot en este canal:**\n"
            + "\n".join(f"• {p}" for p in faltantes)
            + "\n\n**Sin esos permisos, no podré detectar tus reacciones.**\n"
            "Pídele a un admin que los active, o usa el modo chat escribiendo el número."
        )
        return False, msg
    
    return True, None


# =========================================================
# 7. COMANDO /buscar
# =========================================================
@bot.tree.command(name="buscar", description="Busca y elige con reacciones o escribiendo el número.")
@app_commands.describe(query="Nombre de la canción a buscar")
async def buscar(interaction: discord.Interaction, query: str):
    await interaction.response.send_message(f"🔍 Buscando **{query}**...")
    
    # Verificar permisos PRIMERO
    ok_permisos, msg_error = await verificar_permisos_canal(interaction)
    if not ok_permisos:
        await interaction.edit_original_response(content=msg_error)
        return
    
    # Buscar
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
            content=f"❌ Sin resultados para `{query}`."
        )
        return
    
    resultados = resultados[:10]
    
    n_originales = sum(1 for r in resultados if r.get('categoria') == 'ORIGINAL')
    n_otros = len(resultados) - n_originales
    
    descripcion = f"**{len(resultados)} canciones disponibles**"
    if n_originales > 0:
        descripcion += f" · ✅ {n_originales} originales"
    if n_otros > 0:
        descripcion += f" · ⚠️ {n_otros} versiones alternativas"
    
    descripcion += (
        "\n\n**Elige de 2 formas:**\n"
        "• 🎯 **Reacciona** con el emoji numérico\n"
        "• 💬 **Escribe** el número en el chat\n\n"
        "Para cancelar: ❌ o `cancelar`"
    )
    
    embed = discord.Embed(
        title=f"🎵 Resultados para: {query}",
        description=descripcion,
        color=discord.Color.green() if n_originales >= 3 else discord.Color.orange()
    )
    
    for i, r in enumerate(resultados):
        dur = _formatear_duracion(r.get('duracion'))
        titulo = r['titulo'][:80]
        uploader = r.get('uploader', 'Desconocido')[:40]
        categoria = r.get('categoria', 'ORIGINAL')
        
        cat_emoji_map = {
            'ORIGINAL': '✅', 'COVER': '🎤', 'REMIX': '🎧',
            'INSTRUMENTAL': '🎹', 'SLOWED': '🐢', 'SPED UP': '⚡',
            'LIVE': '🎙️', 'MASHUP': '🎛️',
        }
        cat_emoji = cat_emoji_map.get(categoria, '⚠️')
        
        embed.add_field(
            name=f"**{i+1}.** {cat_emoji} {titulo}",
            value=f"⏱️ `{dur}` | 👤 {uploader} | `{categoria}`",
            inline=False
        )
    
    embed.set_footer(text="Tienes 90 segundos para elegir")
    
    mensaje = await interaction.edit_original_response(content=None, embed=embed)
    
    # Añadir reacciones una por una
    print(f"🎯 Añadiendo {len(resultados)} reacciones...")
    reacciones_ok = 0
    for i in range(len(resultados)):
        try:
            await mensaje.add_reaction(EMOJIS_NUMEROS[i])
            reacciones_ok += 1
        except discord.Forbidden:
            await interaction.edit_original_response(
                content=(
                    "❌ **No puedo añadir reacciones en este canal.**\n\n"
                    "**Solución rápida:** Escribe el número directamente en el chat.\n"
                    f"Ejemplo: escribe `1` para elegir la primera canción.\n\n"
                    "O pídele a un admin que active el permiso `Add Reactions`."
                ),
                embed=embed
            )
            # Continuar sin reacciones, solo con modo chat
            break
        except Exception as e:
            print(f"⚠️ Error añadiendo reacción {i}: {e}")
            continue
    
    try:
        await mensaje.add_reaction(EMOJI_CANCELAR)
    except Exception:
        pass
    
    print(f"✅ {reacciones_ok}/{len(resultados)} reacciones añadidas")
    
    # Esperar selección
    idx, forma = await esperar_seleccion(
        interaction, mensaje, len(resultados), timeout=90.0
    )
    
    # Limpiar reacciones
    try:
        await mensaje.clear_reactions()
    except Exception:
        pass
    
    if forma == 'timeout' or idx is None:
        await interaction.edit_original_response(
            content="⏰ Tiempo agotado (90s). Vuelve a usar `/buscar`.",
            embed=None
        )
        return
    
    if forma == 'cancelar' or idx == -1:
        await interaction.edit_original_response(content="❌ Cancelado.", embed=None)
        return
    
    elegido = resultados[idx]
    print(f"🎵 Elegido [{forma}]: {elegido['titulo']}")
    
    await interaction.edit_original_response(
        content=f"⏳ Cargando **{elegido['titulo']}**...",
        embed=None
    )
    
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
    
    # Reproducir SOLO el elegido (sin fallback a otros)
    try:
        loop = asyncio.get_event_loop()
        stream_url, titulo_final = await asyncio.wait_for(
            loop.run_in_executor(None, extraer_stream_de_url_sync, elegido['url']),
            timeout=25.0
        )
    except Exception as e:
        await interaction.edit_original_response(
            content=(
                f"❌ **No se pudo reproducir** `{elegido['titulo'][:60]}`\n"
                f"Motivo: `{str(e)[:100]}`\n\n"
                f"**Prueba eligiendo otra opción** con `/buscar`."
            )
        )
        return
    
    def after_playing(error):
        if error:
            print(f"⚠️ Error: {error}")
    
    try:
        if vc.is_playing():
            vc.stop()
        source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)
        vc.play(source, after=after_playing)
        await interaction.edit_original_response(
            content=f"🎵 Reproduciendo: **{titulo_final}**"
        )
    except Exception as e:
        await interaction.edit_original_response(content=f"❌ Error: {e}")


# =========================================================
# 8. COMANDO /play
# =========================================================
@bot.tree.command(name="play", description="Reproduce el primer ORIGINAL disponible.")
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
        await interaction.edit_original_response(content=f"❌ Sin resultados para `{query}`.")
        return
    
    originales = [r for r in resultados if r.get('categoria') == 'ORIGINAL']
    a_probar = originales + [r for r in resultados if r.get('categoria') != 'ORIGINAL']
    
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
    
    for i, r in enumerate(a_probar):
        cat = r.get('categoria', 'ORIGINAL')
        try:
            await interaction.edit_original_response(
                content=f"⏳ Probando {i+1}/{len(a_probar)} [{cat}]: **{r['titulo'][:55]}**..."
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
            
            aviso = ""
            if cat != 'ORIGINAL':
                aviso = f"\n_(no encontré el original, usé un `{cat}`)_"
            
            await interaction.edit_original_response(
                content=f"🎵 Reproduciendo: **{titulo}**{aviso}"
            )
            return
        except Exception as e:
            print(f"⚠️ Fallo {i+1}: {str(e)[:80]}")
            continue
    
    await interaction.edit_original_response(
        content=f"❌ Ningún resultado reproducible para `{query}`."
    )


# =========================================================
# 9. OTROS COMANDOS
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


@bot.tree.command(name="diagnostico", description="Muestra el estado de los intents y permisos.")
async def diagnostico(interaction: discord.Interaction):
    """Comando para verificar por qué no funcionan las reacciones."""
    embed = discord.Embed(
        title="🔧 Diagnóstico del bot",
        color=discord.Color.blue()
    )
    
    # Intents
    embed.add_field(
        name="Intents activos",
        value=(
            f"• message_content: `{bot.intents.message_content}`\n"
            f"• reactions: `{bot.intents.reactions}`\n"
            f"• voice_states: `{bot.intents.voice_states}`\n"
            f"• guilds: `{bot.intents.guilds}`\n"
            f"• members: `{bot.intents.members}`"
        ),
        inline=False
    )
    
    # Permisos en el canal
    channel = interaction.channel
    if isinstance(channel, (discord.TextChannel, discord.Thread)):
        me = interaction.guild.me
        permisos = channel.permissions_for(me)
        embed.add_field(
            name="Permisos en este canal",
            value=(
                f"• Add Reactions: `{permisos.add_reactions}`\n"
                f"• Read Message History: `{permisos.read_message_history}`\n"
                f"• Send Messages: `{permisos.send_messages}`\n"
                f"• Manage Messages: `{permisos.manage_messages}`\n"
                f"• Embed Links: `{permisos.embed_links}`"
            ),
            inline=False
        )
    
    embed.set_footer(text="Si algo está en False, actívalo en el Developer Portal o en los permisos del canal.")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)


# =========================================================
# 10. EJECUCIÓN
# =========================================================
if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("❌ ERROR: DISCORD_TOKEN no configurado")
        exit(1)
    bot.run(token)
