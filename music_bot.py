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
import time
from dotenv import load_dotenv

load_dotenv()

TEMP_DIR = "temp_audio"
os.makedirs(TEMP_DIR, exist_ok=True)

# Nombre original del bot (para restaurar)
NOMBRE_ORIGINAL = None

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


def _filtro_sin_drm(info_dict, *, incomplete=False):
    if info_dict.get('has_drm'):
        return "DRM protegido (saltado)"
    for f in (info_dict.get('formats') or []):
        if f.get('has_drm'):
            return "DRM protegido (saltado)"
    return None


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
    'match_filter': _filtro_sin_drm,
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
            and not f.get('has_drm')
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


def _buscar_en_proveedor(query: str, proveedor: str, cantidad: int = 15):
    prefijos = {
        'soundcloud': f'scsearch{cantidad}:',
        'bandcamp':   f'bcsearch{cantidad}:',
        'archiveorg': f'iasearch{cantidad}:',
    }
    if proveedor not in prefijos:
        return []
    
    search_query = f'{prefijos[proveedor]}{query}'
    print(f"🔍 [{proveedor}] {search_query}")
    
    try:
        with yt_dlp.YoutubeDL(YDL_OPTIONS_BUSQUEDA) as ydl:
            info = ydl.extract_info(search_query, download=False)
    except Exception as e:
        print(f"⚠️ Error en {proveedor}: {str(e)[:100]}")
        return []
    
    if not info:
        return []
    
    resultados = []
    urls_vistas = set()
    
    for entry in (info.get('entries') or []):
        if not entry:
            continue
        url = entry.get('webpage_url') or entry.get('url')
        if not url or url in urls_vistas:
            continue
        if not entry.get('formats') and not entry.get('url'):
            continue
        if entry.get('has_drm'):
            continue
        
        urls_vistas.add(url)
        resultados.append({
            'titulo': entry.get('title', 'Sin título'),
            'url': url,
            'duracion': entry.get('duration'),
            'uploader': entry.get('uploader', 'Desconocido'),
            'categoria': _clasificar_resultado(entry.get('title', ''), query),
            'proveedor': proveedor,
        })
    
    print(f"   ✅ {len(resultados)} resultados en {proveedor}")
    return resultados


def buscar_resultados_sync(query: str):
    sc_resultados = _buscar_en_proveedor(query, 'soundcloud', 20)
    originales = [r for r in sc_resultados if r['categoria'] == 'ORIGINAL']
    no_originales = [r for r in sc_resultados if r['categoria'] != 'ORIGINAL']
    
    if len(originales) >= 3:
        return originales[:10]
    
    resultados = originales + no_originales
    
    if len(resultados) < 3:
        resultados.extend(_buscar_en_proveedor(query, 'bandcamp', 10))
    if len(resultados) < 3:
        resultados.extend(_buscar_en_proveedor(query, 'archiveorg', 10))
    
    vistos = set()
    unicos = []
    for r in resultados:
        if r['url'] not in vistos:
            vistos.add(r['url'])
            unicos.append(r)
    
    return unicos[:10]


def extraer_stream_de_url_sync(url: str):
    print(f"🎵 Extrayendo: {url[:80]}")
    with yt_dlp.YoutubeDL(YDL_OPTIONS_TRACK) as ydl:
        info = ydl.extract_info(url, download=False)
    
    if not info:
        raise Exception("Info vacío")
    if info.get('has_drm'):
        raise Exception("DRM protegido")
    
    titulo = info.get('title', 'Desconocido')
    duracion = info.get('duration')
    stream_url = _obtener_mejor_url(info)
    
    if not stream_url:
        raise Exception("No se encontró URL de audio")
    
    return stream_url, titulo, duracion


# =========================================================
# 4. BARRA DE PROGRESO
# =========================================================
def generar_barra_progreso(actual: float, total: float, ancho: int = 20) -> str:
    if total <= 0:
        return "▬" * ancho
    progreso = min(actual / total, 1.0)
    pos = int(progreso * ancho)
    pos = min(pos, ancho - 1)
    return "▬" * pos + "🔘" + "▬" * (ancho - pos - 1)


def formatear_tiempo(segundos: float) -> str:
    if segundos is None or segundos < 0:
        return "0:00"
    segundos = int(segundos)
    return f"{segundos // 60}:{segundos % 60:02d}"


class BarraProgreso:
    def __init__(self, bot, interaction, titulo, duracion_total, canal_voz,
                 uploader=None, categoria=None, guild=None):
        self.bot = bot
        self.interaction = interaction
        self.titulo = titulo
        self.duracion_total = duracion_total or 0
        self.canal_voz = canal_voz
        self.uploader = uploader
        self.categoria = categoria
        self.guild = guild
        self.inicio = None
        self.pausado = False
        self.tiempo_pausado = 0
        self.tarea = None
        self.mensaje = None
        self.terminado = False
    
    def iniciar(self):
        self.inicio = time.time()
        self.terminado = False
    
    def pausar(self):
        if not self.pausado:
            self.pausado = True
            self.tiempo_pausado = time.time()
    
    def reanudar(self):
        if self.pausado:
            duracion_pausa = time.time() - self.tiempo_pausado
            self.inicio += duracion_pausa
            self.pausado = False
    
    def obtener_tiempo_actual(self):
        if self.inicio is None:
            return 0
        if self.pausado:
            return self.tiempo_pausado - self.inicio
        return time.time() - self.inicio
    
    def esta_reproduciendo(self):
        return (
            self.canal_voz
            and self.canal_voz.is_playing()
            and not self.terminado
        )
    
    def construir_embed(self):
        actual = self.obtener_tiempo_actual()
        
        if self.duracion_total > 0:
            actual = min(actual, self.duracion_total)
            barra = generar_barra_progreso(actual, self.duracion_total)
            tiempo_texto = f"`{formatear_tiempo(actual)}` / `{formatear_tiempo(self.duracion_total)}`"
        else:
            barra = "🔘" + "▬" * 19
            tiempo_texto = f"`{formatear_tiempo(actual)}` / `🔴 LIVE`"
        
        embed = discord.Embed(
            title="🎵 Reproduciendo ahora",
            description=(
                f"**{self.titulo}**\n\n"
                f"{barra}\n"
                f"{tiempo_texto}"
            ),
            color=discord.Color.green()
        )
        
        if self.uploader:
            embed.add_field(name="👤 Artista", value=self.uploader, inline=True)
        if self.categoria:
            cat_emoji_map = {
                'ORIGINAL': '✅', 'COVER': '🎤', 'REMIX': '🎧',
                'INSTRUMENTAL': '🎹', 'SLOWED': '🐢', 'SPED UP': '⚡',
                'LIVE': '🎙️', 'MASHUP': '🎛️',
            }
            cat_emoji = cat_emoji_map.get(self.categoria, '⚠️')
            embed.add_field(name="🏷️ Tipo", value=f"{cat_emoji} {self.categoria}", inline=True)
        
        embed.set_footer(text="La barra se actualiza cada 5 segundos")
        return embed
    
    async def actualizar_loop(self):
        try:
            await self.actualizar()
            while self.esta_reproduciendo():
                await asyncio.sleep(5)
                if self.esta_reproduciendo():
                    await self.actualizar()
            
            self.terminado = True
            await self.finalizar()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"⚠️ Error en barra de progreso: {e}")
    
    async def actualizar(self):
        try:
            if self.mensaje:
                embed = self.construir_embed()
                await self.mensaje.edit(embed=embed)
        except discord.NotFound:
            self.terminado = True
        except Exception as e:
            print(f"⚠️ Error actualizando barra: {e}")
    
    async def finalizar(self):
        try:
            if self.mensaje:
                embed = discord.Embed(
                    title="✅ Canción terminada",
                    description=f"**{self.titulo}**\n\nYa puedes buscar otra con `/buscar`.",
                    color=discord.Color.greyple()
                )
                await self.mensaje.edit(embed=embed)
        except Exception:
            pass
    
    def detener(self):
        self.terminado = True
        if self.tarea and not self.tarea.done():
            self.tarea.cancel()


barras_activas = {}


# =========================================================
# 5. NICKNAME DINÁMICO
# =========================================================
async def cambiar_nickname_bot(guild, nombre_cancion, categoria=None):
    if guild is None:
        return False
    
    titulo_limpio = nombre_cancion.strip()
    for sufijo in [' - Topic', ' (Official Audio)', ' (Official Video)',
                   ' (Audio)', ' (Lyrics)', ' (Lyric Video)', ' (Official)']:
        if titulo_limpio.endswith(sufijo):
            titulo_limpio = titulo_limpio[:-len(sufijo)].strip()
    
    if categoria == 'COVER':
        prefijo = "🎤 "
    elif categoria == 'REMIX':
        prefijo = "🎧 "
    elif categoria == 'INSTRUMENTAL':
        prefijo = "🎹 "
    elif categoria == 'SLOWED':
        prefijo = "🐢 "
    elif categoria == 'SPED UP':
        prefijo = "⚡ "
    elif categoria == 'LIVE':
        prefijo = "🎙️ "
    else:
        prefijo = "🎵 "
    
    max_len = 32 - len(prefijo)
    if len(titulo_limpio) > max_len:
        titulo_limpio = titulo_limpio[:max_len - 1].rstrip() + "…"
    
    nuevo_nick = f"{prefijo}{titulo_limpio}"
    
    global NOMBRE_ORIGINAL
    if NOMBRE_ORIGINAL is None and guild.me:
        NOMBRE_ORIGINAL = guild.me.display_name
    
    try:
        await guild.me.edit(nick=nuevo_nick)
        print(f"🏷️ Nickname cambiado a: {nuevo_nick}")
        return True
    except discord.Forbidden:
        print("⚠️ No tengo permiso para cambiar mi nickname")
        return False
    except Exception as e:
        print(f"⚠️ Error cambiando nickname: {e}")
        return False


async def restaurar_nickname_bot(guild):
    if guild is None:
        return False
    
    global NOMBRE_ORIGINAL
    
    try:
        await guild.me.edit(nick=NOMBRE_ORIGINAL)
        print("🏷️ Nickname restaurado")
        return True
    except Exception as e:
        print(f"⚠️ Error restaurando nickname: {e}")
        return False


# =========================================================
# 6. BOT
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
        print("✅ Bot iniciado con barra de progreso y nickname dinámico")


bot = MusicBot()


# =========================================================
# 7. ESPERAR SELECCIÓN
# =========================================================
async def esperar_seleccion(interaction, mensaje, cantidad_resultados, timeout=90.0):
    loop = asyncio.get_event_loop()
    futuro_resultado = loop.create_future()
    
    def resolver(indice, forma):
        if not futuro_resultado.done():
            futuro_resultado.set_result((indice, forma))
    
    def check_reaccion(reaction, user):
        return (
            user.id == interaction.user.id
            and not user.bot
            and reaction.message.id == mensaje.id
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
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        except Exception as e:
            print(f"⚠️ Error en listener reacciones: {e}")
    
    def check_mensaje(message):
        if message.author.id != interaction.user.id or message.author.bot:
            return False
        if message.channel.id != interaction.channel_id:
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
            if contenido in ('cancelar', 'cancela', 'cancel', 'x', 'no'):
                resolver(-1, 'cancelar')
            else:
                resolver(int(contenido) - 1, 'chat')
            try:
                await message.delete()
            except Exception:
                pass
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        except Exception as e:
            print(f"⚠️ Error en listener mensajes: {e}")
    
    tarea_reacciones = asyncio.create_task(escuchar_reacciones())
    tarea_mensajes = asyncio.create_task(escuchar_mensajes())
    
    try:
        resultado = await asyncio.wait_for(futuro_resultado, timeout=timeout + 2)
    except asyncio.TimeoutError:
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
# 8. COMANDO /buscar
# =========================================================
@bot.tree.command(name="buscar", description="Busca y elige con reacciones o escribiendo el número.")
@app_commands.describe(query="Nombre de la canción a buscar")
async def buscar(interaction: discord.Interaction, query: str):
    await interaction.response.send_message(f"🔍 Buscando **{query}**...")
    
    try:
        loop = asyncio.get_event_loop()
        resultados = await asyncio.wait_for(
            loop.run_in_executor(None, buscar_resultados_sync, query),
            timeout=90.0
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
                f"❌ **Nada reproducible para** `{query}`\n\n"
                f"**Sugerencias:**\n"
                f"• Añade el artista: `{query} artista`\n"
                f"• Prueba variantes: `/buscar {query} slowed`\n"
                f"• Prueba otro nombre parecido"
            )
        )
        return
    
    resultados = resultados[:10]
    
    n_originales = sum(1 for r in resultados if r.get('categoria') == 'ORIGINAL')
    n_otros = len(resultados) - n_originales
    
    proveedores = {}
    for r in resultados:
        p = r.get('proveedor', 'soundcloud')
        proveedores[p] = proveedores.get(p, 0) + 1
    prov_texto = ' · '.join(f"{p}: {n}" for p, n in proveedores.items())
    
    descripcion = f"**{len(resultados)} canciones disponibles**"
    if n_originales > 0:
        descripcion += f" · ✅ {n_originales} originales"
    if n_otros > 0:
        descripcion += f" · ⚠️ {n_otros} alternativas"
    descripcion += f"\n_Fuente: {prov_texto}_"
    
    descripcion += (
        "\n\n**Elige de 2 formas:**\n"
        "• 🎯 **Reacciona** con el emoji numérico\n"
        "• 💬 **Escribe** el número en el chat\n\n"
        "Cancelar: ❌ o `cancelar`"
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
        proveedor = r.get('proveedor', 'soundcloud')
        
        cat_emoji_map = {
            'ORIGINAL': '✅', 'COVER': '🎤', 'REMIX': '🎧',
            'INSTRUMENTAL': '🎹', 'SLOWED': '🐢', 'SPED UP': '⚡',
            'LIVE': '🎙️', 'MASHUP': '🎛️',
        }
        cat_emoji = cat_emoji_map.get(categoria, '⚠️')
        
        prov_emoji = {'soundcloud': '☁️', 'bandcamp': '🎼', 'archiveorg': '📚'}
        p_emoji = prov_emoji.get(proveedor, '🎵')
        
        embed.add_field(
            name=f"**{i+1}.** {cat_emoji} {titulo}",
            value=f"⏱️ `{dur}` | 👤 {uploader} | `{categoria}` | {p_emoji}",
            inline=False
        )
    
    embed.set_footer(text="Tienes 90 segundos para elegir")
    
    mensaje = await interaction.edit_original_response(content=None, embed=embed)
    
    for i in range(len(resultados)):
        try:
            await mensaje.add_reaction(EMOJIS_NUMEROS[i])
        except discord.Forbidden:
            await interaction.edit_original_response(
                content=(
                    "⚠️ **No puedo añadir reacciones.**\n"
                    "Escribe el número en el chat para elegir."
                ),
                embed=embed
            )
            break
        except Exception as e:
            print(f"⚠️ Error reacción {i}: {e}")
            continue
    
    try:
        await mensaje.add_reaction(EMOJI_CANCELAR)
    except Exception:
        pass
    
    idx, forma = await esperar_seleccion(
        interaction, mensaje, len(resultados), timeout=90.0
    )
    
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
    
    await interaction.edit_original_response(
        content=f"⏳ Cargando **{elegido['titulo']}**...",
        embed=None
    )
    
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
    
    try:
        loop = asyncio.get_event_loop()
        stream_url, titulo_final, duracion = await asyncio.wait_for(
            loop.run_in_executor(None, extraer_stream_de_url_sync, elegido['url']),
            timeout=25.0
        )
    except Exception as e:
        await interaction.edit_original_response(
            content=(
                f"❌ **No se pudo reproducir** `{elegido['titulo'][:60]}`\n"
                f"Motivo: `{str(e)[:100]}`\n\n"
                f"Prueba con otra opción."
            )
        )
        return
    
    guild_id = interaction.guild.id
    guild = interaction.guild
    
    if guild_id in barras_activas:
        barras_activas[guild_id].detener()
        del barras_activas[guild_id]
    
    barra = BarraProgreso(
        bot=bot,
        interaction=interaction,
        titulo=titulo_final,
        duracion_total=duracion or elegido.get('duracion'),
        canal_voz=vc,
        uploader=elegido.get('uploader'),
        categoria=elegido.get('categoria'),
        guild=guild,
    )
    
    def after_playing(error):
        if error:
            print(f"⚠️ Error reproduciendo: {error}")
        if guild_id in barras_activas:
            barras_activas[guild_id].detener()
            del barras_activas[guild_id]
        asyncio.run_coroutine_threadsafe(
            restaurar_nickname_bot(guild),
            bot.loop
        )
    
    try:
        if vc.is_playing():
            vc.stop()
        
        source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)
        vc.play(source, after=after_playing)
        
        await cambiar_nickname_bot(guild, titulo_final, elegido.get('categoria'))
        
        embed_inicial = barra.construir_embed()
        await interaction.edit_original_response(content=None, embed=embed_inicial)
        barra.mensaje = await interaction.original_response()
        
        barra.iniciar()
        barra.tarea = asyncio.create_task(barra.actualizar_loop())
        barras_activas[guild_id] = barra
        
        print(f"▶️ Reproduciendo: {titulo_final} ({_formatear_duracion(duracion)})")
    except Exception as e:
        await interaction.edit_original_response(content=f"❌ Error: {e}")


# =========================================================
# 9. COMANDO /play
# =========================================================
@bot.tree.command(name="play", description="Reproduce el primer resultado disponible.")
@app_commands.describe(query="Nombre de la canción")
async def play(interaction: discord.Interaction, query: str):
    await interaction.response.send_message(f"⏳ Buscando **{query}**...")
    
    try:
        loop = asyncio.get_event_loop()
        resultados = await asyncio.wait_for(
            loop.run_in_executor(None, buscar_resultados_sync, query),
            timeout=90.0
        )
    except Exception as e:
        await interaction.edit_original_response(content=f"❌ Error: {str(e)[:300]}")
        return
    
    if not resultados:
        await interaction.edit_original_response(
            content=f"❌ Sin resultados reproducibles para `{query}`."
        )
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
    guild = interaction.guild
    guild_id = guild.id
    
    for i, r in enumerate(a_probar):
        cat = r.get('categoria', 'ORIGINAL')
        try:
            await interaction.edit_original_response(
                content=f"⏳ Probando {i+1}/{len(a_probar)} [{cat}]: **{r['titulo'][:55]}**..."
            )
            loop = asyncio.get_event_loop()
            stream_url, titulo, duracion = await asyncio.wait_for(
                loop.run_in_executor(None, extraer_stream_de_url_sync, r['url']),
                timeout=20.0
            )
            
            if guild_id in barras_activas:
                barras_activas[guild_id].detener()
                del barras_activas[guild_id]
            
            barra = BarraProgreso(
                bot=bot,
                interaction=interaction,
                titulo=titulo,
                duracion_total=duracion or r.get('duracion'),
                canal_voz=vc,
                uploader=r.get('uploader'),
                categoria=cat,
                guild=guild,
            )
            
            def after_playing(error):
                if error:
                    print(f"⚠️ Error: {error}")
                if guild_id in barras_activas:
                    barras_activas[guild_id].detener()
                    del barras_activas[guild_id]
                asyncio.run_coroutine_threadsafe(
                    restaurar_nickname_bot(guild),
                    bot.loop
                )
            
            if vc.is_playing():
                vc.stop()
            
            source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)
            vc.play(source, after=after_playing)
            
            await cambiar_nickname_bot(guild, titulo, cat)
            
