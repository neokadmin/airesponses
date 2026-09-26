import discord
from discord.ext import commands
from discord.ext import voice_recv
from discord import app_commands
import yt_dlp
import os
import asyncio
import shutil
import tempfile
from dotenv import load_dotenv

load_dotenv()

def load_opus_lib():
    if discord.opus.is_loaded():
        return True
    paths = [
        "/mnt/nix/store/wd207v6gnbdjhxlshyxqhvd1x978bgvw-user-environment/lib/libopus.so.0",
        "/mnt/nix/store/hl5cqxz44gaz28y6k75qd9g2yfy1hdrg-user-environment/lib/libopus.so.0",
        "libopus.so.0"
    ]
    for path in paths:
        if os.path.exists(path) or path == "libopus.so.0":
            try:
                discord.opus.load_opus(path)
                return True
            except:
                continue
    return False

load_opus_lib()

YDL_OPTIONS = {
    'format': 'best[acodec!=none]/best',
    'noplaylist': True,
    'quiet': True,
    'noprogress': True,
    'ignoreerrors': True,
    'nocheckcertificate': True,
    'socket_timeout': 10,
    'js_runtimes': {'node': {}},
    'extractor_args': {
        'youtube': {
            'player_client': ['web'],
        },
    },
}

FFMPEG_OPTIONS = {
    'options': '-vn'
}

youtube_cookie_file = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "tst.txt",
)
if os.path.isfile(youtube_cookie_file):
    YDL_OPTIONS["cookiefile"] = youtube_cookie_file

PUBLIC_YDL_OPTIONS = {
    key: value for key, value in YDL_OPTIONS.items() if key != "cookiefile"
}
youtube_cookies_disabled_for_session = False

background_monitors = {}


class VoiceActivitySink(voice_recv.AudioSink):
    def wants_opus(self):
        return True

    def write(self, user, data):
        return None

    def cleanup(self):
        return None


def enable_voice_receive(vc):
    if isinstance(vc, voice_recv.VoiceRecvClient) and not vc.is_listening():
        vc.listen(VoiceActivitySink())


def stop_background_monitor(guild_id):
    task = background_monitors.pop(guild_id, None)
    if task and not task.done():
        task.cancel()


async def monitor_background(guild_id, vc):
    try:
        while vc.is_connected() and (vc.is_playing() or vc.is_paused()):
            speaking = any(
                member.id != bot.user.id
                and member.voice
                and member.voice.channel == vc.channel
                and vc.get_speaking(member) is True
                for member in vc.channel.members
            )

            if speaking and vc.is_playing():
                vc.pause()
            elif not speaking and vc.is_paused():
                vc.resume()

            await asyncio.sleep(0.15)
    except asyncio.CancelledError:
        raise
    finally:
        if background_monitors.get(guild_id) is asyncio.current_task():
            background_monitors.pop(guild_id, None)


async def connect_to_voice(guild, channel):
    vc = guild.voice_client
    if vc and not vc.is_connected():
        try:
            await vc.disconnect(force=True)
        except Exception:
            pass
        vc = None

    if vc and not isinstance(vc, voice_recv.VoiceRecvClient):
        await vc.disconnect(force=True)
        vc = None

    if not vc:
        vc = await channel.connect(
            cls=voice_recv.VoiceRecvClient,
            timeout=15.0,
            reconnect=True,
        )
    elif vc.channel != channel:
        await vc.move_to(channel)

    enable_voice_receive(vc)
    return vc


def extract_track(search_query, ydl_options):
    with yt_dlp.YoutubeDL(ydl_options) as search_ydl:
        result = search_ydl.extract_info(search_query, download=False)
    if not result:
        raise Exception("No se encontró información para esta búsqueda en YouTube.")

    entries = result.get("entries") if "entries" in result else [result]
    entries = [entry for entry in entries if entry]
    if not entries:
        raise Exception("No se encontraron resultados en YouTube.")

    last_error = None
    for info in entries:
        temp_dir = tempfile.mkdtemp(prefix="music-bot-")
        download_options = {
            **ydl_options,
            "outtmpl": os.path.join(temp_dir, "%(id)s.%(ext)s"),
            "noplaylist": True,
        }
        try:
            with yt_dlp.YoutubeDL(download_options) as ydl:
                webpage_url = info.get("webpage_url") or info.get("url")
                if not webpage_url:
                    raise Exception("Resultado sin enlace reproducible.")
                ydl.download([webpage_url])
                downloaded_files = [
                    os.path.join(temp_dir, name)
                    for name in os.listdir(temp_dir)
                    if os.path.isfile(os.path.join(temp_dir, name))
                ]
                if not downloaded_files:
                    raise Exception("La pista no se pudo descargar.")
                return (
                    downloaded_files[0],
                    info.get("title", "Desconocido"),
                    temp_dir,
                )
        except Exception as error:
            last_error = error
            shutil.rmtree(temp_dir, ignore_errors=True)
            continue

    raise Exception(
        f"No se encontró una pista reproducible. "
        f"YouTube no entregó un formato de audio reproducible. "
        f"Último error: {last_error}"
    )


async def download_track(query):
    global youtube_cookies_disabled_for_session

    search_query = query if query.startswith("http") else f"ytsearch5:{query}"
    loop = asyncio.get_running_loop()
    options = (
        PUBLIC_YDL_OPTIONS
        if youtube_cookies_disabled_for_session
        else YDL_OPTIONS
    )

    try:
        return await loop.run_in_executor(None, extract_track, search_query, options)
    except Exception:
        if "cookiefile" not in YDL_OPTIONS or options is PUBLIC_YDL_OPTIONS:
            raise

        youtube_cookies_disabled_for_session = True
        print(
            "Las cookies de YouTube no son válidas; "
            "se usará acceso público para las siguientes pistas."
        )
        return await loop.run_in_executor(
            None,
            extract_track,
            search_query,
            PUBLIC_YDL_OPTIONS,
        )


intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

class MusicBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print("Bot iniciado y comandos sincronizados.")

bot = MusicBot()

@bot.tree.command(name="join", description="Conecta el bot al canal de voz")
async def join(interaction: discord.Interaction):
    if not interaction.user.voice:
        return await interaction.response.send_message("¡Únete a un canal de voz!", ephemeral=True)
    
    await interaction.response.defer(ephemeral=True)
    channel = interaction.user.voice.channel
    
    try:
        await connect_to_voice(interaction.guild, channel)
        await interaction.followup.send("Conectado al canal de voz.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"No pude conectar al canal de voz: {str(e)}", ephemeral=True)

@bot.tree.command(name="play", description="Reproduce música de YouTube (Nombre o URL)")
@app_commands.describe(query="Nombre de la canción o enlace de YouTube", volume="Volumen (1-100)")
async def play(interaction: discord.Interaction, query: str, volume: int = 50):
    await interaction.response.defer(ephemeral=True)
    
    if not interaction.user.voice:
        return await interaction.followup.send("¡Primero debes unirte a un canal de voz!", ephemeral=True)

    channel = interaction.user.voice.channel
    stop_background_monitor(interaction.guild.id)

    try:
        vc = await connect_to_voice(interaction.guild, channel)
    except Exception as e:
        return await interaction.followup.send(f"Error de conexión de voz: {str(e)}", ephemeral=True)

    vol = max(1, min(100, volume)) / 100.0

    try:
        file_path, title, temp_dir = await download_track(query)
    except Exception as e:
        return await interaction.followup.send(f"Error al buscar la canción: {str(e)}", ephemeral=True)

    if not vc.is_connected():
        try:
            await vc.disconnect(force=True)
        except Exception:
            pass
        try:
            vc = await connect_to_voice(interaction.guild, channel)
        except Exception as error:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return await interaction.followup.send(
                f"No pude reconectar al canal de voz: {error}",
                ephemeral=True,
            )

    if not vc.is_connected():
        shutil.rmtree(temp_dir, ignore_errors=True)
        return await interaction.followup.send(
            "La conexión de voz se perdió. Vuelve a intentar /play.",
            ephemeral=True,
        )

    if vc.is_playing() or vc.is_paused():
        vc.stop()

    try:
        await interaction.guild.me.edit(nick=title[:32])
    except:
        pass

    source = discord.PCMVolumeTransformer(
        discord.FFmpegPCMAudio(file_path, **FFMPEG_OPTIONS),
        volume=vol,
    )

    def cleanup(_error):
        shutil.rmtree(temp_dir, ignore_errors=True)

    try:
        vc.play(source, after=cleanup)
    except discord.ClientException:
        cleanup(None)
        return await interaction.followup.send(
            "La conexión de voz se perdió antes de reproducir la pista. "
            "Vuelve a intentar /play.",
            ephemeral=True,
        )
    
    await interaction.followup.send(f"🎶 Reproduciendo desde YouTube: **{title}** al {volume}%", ephemeral=True)


@bot.tree.command(
    name="background",
    description="Reproduce música de fondo con control de voz",
)
@app_commands.describe(
    query="Nombre de la canción o enlace de YouTube",
    tipo="1: pausa cuando alguien habla; 2: suena siempre bajito",
)
async def background(interaction: discord.Interaction, query: str, tipo: int = 1):
    await interaction.response.defer(ephemeral=True)

    if tipo not in (1, 2):
        return await interaction.followup.send(
            "El tipo debe ser 1 o 2.",
            ephemeral=True,
        )

    if not interaction.user.voice:
        return await interaction.followup.send(
            "¡Primero debes unirte a un canal de voz!",
            ephemeral=True,
        )

    channel = interaction.user.voice.channel
    stop_background_monitor(interaction.guild.id)

    try:
        vc = await connect_to_voice(interaction.guild, channel)
    except Exception as error:
        return await interaction.followup.send(
            f"Error de conexión de voz: {error}",
            ephemeral=True,
        )

    volume = 0.20 if tipo == 1 else 0.10

    try:
        file_path, title, temp_dir = await download_track(query)
    except Exception as error:
        return await interaction.followup.send(
            f"Error al buscar la canción: {error}",
            ephemeral=True,
        )

    if not vc.is_connected():
        try:
            vc = await connect_to_voice(interaction.guild, channel)
        except Exception as error:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return await interaction.followup.send(
                f"No pude reconectar al canal de voz: {error}",
                ephemeral=True,
            )

    if not vc.is_connected():
        shutil.rmtree(temp_dir, ignore_errors=True)
        return await interaction.followup.send(
            "La conexión de voz se perdió. Vuelve a intentar /background.",
            ephemeral=True,
        )

    if vc.is_playing() or vc.is_paused():
        vc.stop()

    try:
        await interaction.guild.me.edit(nick=title[:32])
    except Exception:
        pass

    source = discord.PCMVolumeTransformer(
        discord.FFmpegPCMAudio(file_path, **FFMPEG_OPTIONS),
        volume=volume,
    )

    def cleanup(_error):
        shutil.rmtree(temp_dir, ignore_errors=True)

    try:
        vc.play(source, after=cleanup)
    except discord.ClientException:
        cleanup(None)
        return await interaction.followup.send(
            "La conexión de voz se perdió antes de reproducir la música de fondo.",
            ephemeral=True,
        )

    if tipo == 1:
        background_monitors[interaction.guild.id] = asyncio.create_task(
            monitor_background(interaction.guild.id, vc)
        )
        mode_message = "se pausa automáticamente cuando alguien habla"
    else:
        mode_message = "suena continuamente a volumen bajo"

    await interaction.followup.send(
        f"🎵 Música de fondo desde YouTube: **{title}**; {mode_message}.",
        ephemeral=True,
    )


@bot.tree.command(name="leave", description="Desconecta el bot")
async def leave(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        stop_background_monitor(interaction.guild.id)
        try:
            await interaction.guild.me.edit(nick=None)
        except:
            pass
        await interaction.guild.voice_client.disconnect(force=True)
        await interaction.response.send_message("Desconectado.", ephemeral=True)
    else:
        await interaction.response.send_message("No estoy en ningún canal.", ephemeral=True)

bot.run(os.getenv("DISCORD_TOKEN"))
