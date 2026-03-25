"""
Discord Music Bot
Supports YouTube and Spotify links, playlists, and displays track info with author
"""

import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import yt_dlp
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import re
from collections import deque
from dataclasses import dataclass
from typing import Optional
import os
import sys
import logging

# ============== Logging Setup ==============
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), "uta.log")),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("UtaBot")

# ============== Load .env file if exists ==============
def load_env():
    """Load environment variables from .env file"""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    logger.info(f"Looking for .env at: {env_path} (exists: {os.path.exists(env_path)})")
    logger.info(f"Working directory: {os.getcwd()}")
    logger.info(f"Script directory: {os.path.dirname(os.path.abspath(__file__))}")
    if os.path.exists(env_path):
        logger.info("Loading configuration from .env file...")
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    # Remove quotes if present
                    value = value.strip().strip('"').strip("'")
                    os.environ[key.strip()] = value
    else:
        logger.warning(".env file NOT found — relying on environment variables")

load_env()

# ============== Configuration ==============
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
logger.info(f"DISCORD_TOKEN loaded: {'YES (len=' + str(len(DISCORD_TOKEN)) + ')' if DISCORD_TOKEN else 'NO - MISSING'}")
logger.info(f"SPOTIFY_CLIENT_ID loaded: {'YES' if SPOTIFY_CLIENT_ID else 'NO (optional)'}")
logger.info(f"Python version: {sys.version}")
logger.info(f"discord.py version: {discord.__version__}")

# ============== Validate Token ==============
def validate_config():
    """Check if required configuration is set"""
    if not DISCORD_TOKEN or DISCORD_TOKEN in ["your_discord_bot_token_here", "YOUR_DISCORD_BOT_TOKEN"]:
        print()
        print("=" * 60)
        print("❌ ERROR: Discord bot token is not configured!")
        print("=" * 60)
        print()
        print("To fix this, create a .env file:")
        print("-" * 40)
        print("1. Create a file named '.env' in the same folder as bot.py")
        print("2. Add this line (replace with your actual token):")
        print()
        print("   DISCORD_TOKEN=MTIzNDU2Nzg5MDEyMzQ1Njc4OQ.XXXXXX.XXXXXXXXX")
        print()
        print("=" * 60)
        print("HOW TO GET YOUR BOT TOKEN:")
        print("=" * 60)
        print("1. Go to: https://discord.com/developers/applications")
        print("2. Click 'New Application' or select your existing bot")
        print("3. Go to 'Bot' section in the left sidebar")
        print("4. Click 'Reset Token' button and confirm")
        print("5. Copy the token that appears (looks like above)")
        print()
        print("⚠️  IMPORTANT SETTINGS TO ENABLE:")
        print("   - In Bot section: Enable 'MESSAGE CONTENT INTENT'")
        print("   - In Bot section: Enable 'SERVER MEMBERS INTENT' (optional)")
        print("=" * 60)
        print()
        sys.exit(1)
    else:
        token_preview = DISCORD_TOKEN[:20] + "..." if len(DISCORD_TOKEN) > 20 else "***"
        logger.info(f"Discord token loaded: {token_preview}")

validate_config()

# ============== YT-DLP Options ==============
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'audioformat': 'mp3',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': False,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

# ============== Data Classes ==============
@dataclass
class Song:
    title: str
    author: str
    url: str
    source_url: str = ""
    duration: str = ""
    thumbnail: str = ""
    requester: str = ""

    def __str__(self):
        return f"**{self.title}** by **{self.author}**"

# ============== Music Queue ==============
class MusicQueue:
    def __init__(self):
        self.queue: deque[Song] = deque()
        self.current: Optional[Song] = None
        self.loop: bool = False
        self.loop_queue: bool = False

    def add(self, song: Song):
        self.queue.append(song)

    def next(self) -> Optional[Song]:
        if self.loop and self.current:
            return self.current
        if self.loop_queue and self.current:
            self.queue.append(self.current)
        if self.queue:
            self.current = self.queue.popleft()
            return self.current
        self.current = None
        return None

    def clear(self):
        self.queue.clear()
        self.current = None

    def __len__(self):
        return len(self.queue)

# ============== YouTube Handler ==============
class YouTubeHandler:
    def __init__(self):
        self.ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

    async def extract_info(self, url: str, search: bool = False) -> list[Song]:
        loop = asyncio.get_event_loop()

        if search:
            url = f"ytsearch:{url}"

        try:
            data = await loop.run_in_executor(
                None, lambda: self.ytdl.extract_info(url, download=False)
            )
        except Exception as e:
            logger.error(f"Error extracting info for '{url}': {e}", exc_info=True)
            return []

        songs = []

        if 'entries' in data:
            # Playlist
            for entry in data['entries']:
                if entry:
                    song = self._create_song(entry)
                    if song:
                        songs.append(song)
        else:
            # Single video
            song = self._create_song(data)
            if song:
                songs.append(song)

        return songs

    def _create_song(self, data: dict) -> Optional[Song]:
        if not data:
            return None

        duration_seconds = data.get('duration', 0)
        if duration_seconds:
            minutes, seconds = divmod(duration_seconds, 60)
            hours, minutes = divmod(minutes, 60)
            if hours:
                duration = f"{hours}:{minutes:02d}:{seconds:02d}"
            else:
                duration = f"{minutes}:{seconds:02d}"
        else:
            duration = "Unknown"

        return Song(
            title=data.get('title', 'Unknown Title'),
            author=data.get('uploader', data.get('artist', 'Unknown Artist')),
            url=data.get('webpage_url', data.get('url', '')),
            source_url=data.get('url', ''),
            duration=duration,
            thumbnail=data.get('thumbnail', '')
        )

    async def get_stream_url(self, url: str) -> Optional[str]:
        loop = asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(
                None, lambda: self.ytdl.extract_info(url, download=False)
            )
            return data.get('url')
        except Exception as e:
            logger.error(f"Error getting stream URL for '{url}': {e}", exc_info=True)
            return None

# ============== Spotify Handler ==============
class SpotifyHandler:
    def __init__(self):
        self.enabled = False
        if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
            try:
                self.sp = spotipy.Spotify(
                    auth_manager=SpotifyClientCredentials(
                        client_id=SPOTIFY_CLIENT_ID,
                        client_secret=SPOTIFY_CLIENT_SECRET
                    )
                )
                self.enabled = True
                logger.info("Spotify integration enabled")
            except Exception as e:
                logger.error(f"Spotify initialization failed: {e}", exc_info=True)
        else:
            logger.info("Spotify not configured (optional - YouTube will still work)")

    def is_spotify_url(self, url: str) -> bool:
        return 'spotify.com' in url or 'open.spotify.com' in url

    def get_track_info(self, url: str) -> list[dict]:
        if not self.enabled:
            return []

        tracks = []

        try:
            if '/track/' in url:
                # Single track
                track_id = self._extract_id(url)
                track = self.sp.track(track_id)
                tracks.append({
                    'title': track['name'],
                    'author': ', '.join(artist['name'] for artist in track['artists']),
                    'duration_ms': track['duration_ms']
                })

            elif '/artist/' in url:
                # Artist - get top tracks
                artist_id = self._extract_id(url)
                artist_info = self.sp.artist(artist_id)
                artist_name = artist_info['name']

                # Get top tracks (returns up to 10)
                top_tracks = self.sp.artist_top_tracks(artist_id, country='US')

                for track in top_tracks['tracks']:
                    tracks.append({
                        'title': track['name'],
                        'author': ', '.join(artist['name'] for artist in track['artists']),
                        'duration_ms': track['duration_ms']
                    })

                # Optionally get more from albums
                # Get artist's albums
                albums = self.sp.artist_albums(artist_id, album_type='album,single', limit=5)

                for album in albums['items']:
                    album_tracks = self.sp.album_tracks(album['id'])
                    for track in album_tracks['items'][:3]:  # Get top 3 from each album
                        track_info = {
                            'title': track['name'],
                            'author': ', '.join(artist['name'] for artist in track['artists']),
                            'duration_ms': track['duration_ms']
                        }
                        # Avoid duplicates
                        if not any(t['title'] == track_info['title'] for t in tracks):
                            tracks.append(track_info)

            elif '/playlist/' in url:
                # Playlist
                playlist_id = self._extract_id(url)
                results = self.sp.playlist_tracks(playlist_id)

                while results:
                    for item in results['items']:
                        track = item.get('track')
                        if track:
                            tracks.append({
                                'title': track['name'],
                                'author': ', '.join(artist['name'] for artist in track['artists']),
                                'duration_ms': track['duration_ms']
                            })

                    if results['next']:
                        results = self.sp.next(results)
                    else:
                        break

            elif '/album/' in url:
                # Album
                album_id = self._extract_id(url)
                results = self.sp.album_tracks(album_id)
                album_info = self.sp.album(album_id)

                for track in results['items']:
                    tracks.append({
                        'title': track['name'],
                        'author': ', '.join(artist['name'] for artist in track['artists']),
                        'duration_ms': track['duration_ms']
                    })

        except Exception as e:
            logger.error(f"Error fetching Spotify info for '{url}': {e}", exc_info=True)

        return tracks

    def _extract_id(self, url: str) -> str:
        # Extract ID from Spotify URL
        pattern = r'(track|playlist|album|artist)/([a-zA-Z0-9]+)'
        match = re.search(pattern, url)
        if match:
            return match.group(2)
        return url

# ============== Music Cog ==============
class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.queues: dict[int, MusicQueue] = {}
        self.youtube = YouTubeHandler()
        self.spotify = SpotifyHandler()

    def get_queue(self, guild_id: int) -> MusicQueue:
        if guild_id not in self.queues:
            self.queues[guild_id] = MusicQueue()
        return self.queues[guild_id]

    async def play_next(self, guild: discord.Guild):
        queue = self.get_queue(guild.id)
        voice_client = guild.voice_client

        if not voice_client or not voice_client.is_connected():
            logger.warning(f"[{guild.name}] play_next called but bot is not in a voice channel")
            return

        song = queue.next()
        if not song:
            logger.info(f"[{guild.name}] Queue empty, waiting 3 minutes before disconnecting")
            await asyncio.sleep(180)
            if not queue.current and voice_client.is_connected():
                logger.info(f"[{guild.name}] Disconnecting due to inactivity")
                await voice_client.disconnect()
            return

        logger.info(f"[{guild.name}] Now playing: {song.title} by {song.author}")

        try:
            if not song.source_url:
                logger.info(f"[{guild.name}] Fetching stream URL for: {song.url}")
                stream_url = await self.youtube.get_stream_url(song.url)
                if not stream_url:
                    logger.warning(f"[{guild.name}] No stream URL, searching by title: {song.title} {song.author}")
                    songs = await self.youtube.extract_info(f"{song.title} {song.author}", search=True)
                    if songs:
                        song = songs[0]
                        stream_url = song.source_url or await self.youtube.get_stream_url(song.url)
            else:
                stream_url = song.source_url

            if not stream_url:
                logger.error(f"[{guild.name}] Could not get stream URL for '{song.title}', skipping")
                await self.play_next(guild)
                return

            logger.info(f"[{guild.name}] Starting FFmpeg for: {song.title}")
            source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)

            def after_playing(error):
                if error:
                    logger.error(f"[{guild.name}] Player error after '{song.title}': {error}")
                else:
                    logger.info(f"[{guild.name}] Finished playing: {song.title}")
                asyncio.run_coroutine_threadsafe(self.play_next(guild), self.bot.loop)

            voice_client.play(source, after=after_playing)

        except Exception as e:
            logger.error(f"[{guild.name}] Exception while playing '{song.title}': {e}", exc_info=True)
            await self.play_next(guild)

    @commands.hybrid_command(name="join", description="Join your voice channel")
    async def join(self, ctx: commands.Context):
        if not ctx.author.voice:
            return await ctx.send("❌ You need to be in a voice channel!")

        channel = ctx.author.voice.channel
        logger.info(f"[{ctx.guild.name}] Joining voice channel: {channel.name} (requested by {ctx.author})")

        try:
            if ctx.voice_client:
                logger.info(f"[{ctx.guild.name}] Moving to channel: {channel.name}")
                await ctx.voice_client.move_to(channel)
            else:
                await channel.connect()
                logger.info(f"[{ctx.guild.name}] Successfully connected to: {channel.name}")
        except Exception as e:
            logger.error(f"[{ctx.guild.name}] Failed to join voice channel '{channel.name}': {e}", exc_info=True)
            return await ctx.send(f"❌ Failed to join: {e}")

        await ctx.send(f"🎵 Joined **{channel.name}**")

    @commands.hybrid_command(name="leave", description="Leave the voice channel")
    async def leave(self, ctx: commands.Context):
        if not ctx.voice_client:
            return await ctx.send("❌ I'm not in a voice channel!")

        queue = self.get_queue(ctx.guild.id)
        queue.clear()
        await ctx.voice_client.disconnect()
        await ctx.send("👋 Left the voice channel")

    @commands.hybrid_command(name="play", description="Play a song from YouTube or Spotify")
    @app_commands.describe(query="YouTube/Spotify URL or search query")
    async def play(self, ctx: commands.Context, *, query: str):
        if not ctx.author.voice:
            return await ctx.send("❌ You need to be in a voice channel!")

        # Join voice channel if not connected
        if not ctx.voice_client:
            await ctx.author.voice.channel.connect()

        queue = self.get_queue(ctx.guild.id)

        await ctx.defer()

        songs_to_add = []

        # Check if Spotify URL
        if self.spotify.is_spotify_url(query):
            if not self.spotify.enabled:
                return await ctx.send("❌ Spotify is not configured! Add SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET to your .env file to use Spotify links.")

            tracks = self.spotify.get_track_info(query)
            if not tracks:
                return await ctx.send("❌ Could not find any tracks from that Spotify link!")

            await ctx.send(f"🎵 Processing **{len(tracks)}** track(s) from Spotify...")

            for track in tracks:
                # Search on YouTube
                search_query = f"{track['title']} {track['author']}"
                yt_songs = await self.youtube.extract_info(search_query, search=True)
                if yt_songs:
                    song = yt_songs[0]
                    song.title = track['title']
                    song.author = track['author']
                    song.requester = ctx.author.display_name
                    songs_to_add.append(song)

        # Check if YouTube URL
        elif 'youtube.com' in query or 'youtu.be' in query:
            songs = await self.youtube.extract_info(query)
            if not songs:
                return await ctx.send("❌ Could not find any songs!")

            for song in songs:
                song.requester = ctx.author.display_name
                songs_to_add.append(song)

        # Search query
        else:
            songs = await self.youtube.extract_info(query, search=True)
            if not songs:
                return await ctx.send("❌ No results found!")

            songs[0].requester = ctx.author.display_name
            songs_to_add.append(songs[0])

        # Add songs to queue
        for song in songs_to_add:
            queue.add(song)

        # Create response embed
        if len(songs_to_add) == 1:
            song = songs_to_add[0]
            embed = discord.Embed(
                title="🎵 Added to Queue",
                description=str(song),
                color=discord.Color.green()
            )
            embed.add_field(name="Duration", value=song.duration, inline=True)
            embed.add_field(name="Position", value=f"#{len(queue)}", inline=True)
            embed.add_field(name="Requested by", value=song.requester, inline=True)
            if song.thumbnail:
                embed.set_thumbnail(url=song.thumbnail)
        else:
            embed = discord.Embed(
                title="🎵 Added to Queue",
                description=f"Added **{len(songs_to_add)}** songs to the queue",
                color=discord.Color.green()
            )
            embed.add_field(name="Requested by", value=ctx.author.display_name, inline=True)

        await ctx.send(embed=embed)

        # Start playing if not already
        if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
            await self.play_next(ctx.guild)

    @commands.hybrid_command(name="skip", description="Skip the current song")
    async def skip(self, ctx: commands.Context):
        if not ctx.voice_client or not ctx.voice_client.is_playing():
            return await ctx.send("❌ Nothing is playing!")

        ctx.voice_client.stop()
        await ctx.send("⏭️ Skipped!")

    @commands.hybrid_command(name="pause", description="Pause the current song")
    async def pause(self, ctx: commands.Context):
        if not ctx.voice_client:
            return await ctx.send("❌ I'm not in a voice channel!")

        if ctx.voice_client.is_paused():
            return await ctx.send("⏸️ Already paused!")

        ctx.voice_client.pause()
        await ctx.send("⏸️ Paused")

    @commands.hybrid_command(name="resume", description="Resume the current song")
    async def resume(self, ctx: commands.Context):
        if not ctx.voice_client:
            return await ctx.send("❌ I'm not in a voice channel!")

        if not ctx.voice_client.is_paused():
            return await ctx.send("▶️ Not paused!")

        ctx.voice_client.resume()
        await ctx.send("▶️ Resumed")

    @commands.hybrid_command(name="stop", description="Stop playing and clear the queue")
    async def stop(self, ctx: commands.Context):
        if not ctx.voice_client:
            return await ctx.send("❌ I'm not in a voice channel!")

        queue = self.get_queue(ctx.guild.id)
        queue.clear()
        ctx.voice_client.stop()
        await ctx.send("⏹️ Stopped and cleared the queue")

    @commands.hybrid_command(name="queue", description="Show the current queue")
    async def queue_cmd(self, ctx: commands.Context):
        queue = self.get_queue(ctx.guild.id)

        if not queue.current and len(queue) == 0:
            return await ctx.send("📭 The queue is empty!")

        embed = discord.Embed(
            title="🎵 Music Queue",
            color=discord.Color.blue()
        )

        if queue.current:
            embed.add_field(
                name="Now Playing",
                value=f"{queue.current}\n`{queue.current.duration}` | Requested by {queue.current.requester}",
                inline=False
            )

        if len(queue) > 0:
            queue_list = []
            for i, song in enumerate(list(queue.queue)[:10], 1):
                queue_list.append(f"`{i}.` {song} - `{song.duration}`")

            remaining = len(queue) - 10
            if remaining > 0:
                queue_list.append(f"\n*...and {remaining} more*")

            embed.add_field(
                name=f"Up Next ({len(queue)} songs)",
                value="\n".join(queue_list),
                inline=False
            )

        # Show loop status
        status = []
        if queue.loop:
            status.append("🔂 Loop: ON")
        if queue.loop_queue:
            status.append("🔁 Queue Loop: ON")
        if status:
            embed.set_footer(text=" | ".join(status))

        await ctx.send(embed=embed)

    @commands.hybrid_command(name="nowplaying", aliases=["np"], description="Show the current song")
    async def nowplaying(self, ctx: commands.Context):
        queue = self.get_queue(ctx.guild.id)

        if not queue.current:
            return await ctx.send("❌ Nothing is playing!")

        song = queue.current
        embed = discord.Embed(
            title="🎵 Now Playing",
            description=str(song),
            color=discord.Color.purple()
        )
        embed.add_field(name="Duration", value=song.duration, inline=True)
        embed.add_field(name="Requested by", value=song.requester, inline=True)
        if song.thumbnail:
            embed.set_thumbnail(url=song.thumbnail)
        if song.url:
            embed.add_field(name="Link", value=f"[Click here]({song.url})", inline=True)

        await ctx.send(embed=embed)

    @commands.hybrid_command(name="loop", description="Toggle loop for current song")
    async def loop(self, ctx: commands.Context):
        queue = self.get_queue(ctx.guild.id)
        queue.loop = not queue.loop
        queue.loop_queue = False

        status = "enabled 🔂" if queue.loop else "disabled"
        await ctx.send(f"Loop {status}")

    @commands.hybrid_command(name="loopqueue", aliases=["lq"], description="Toggle loop for the entire queue")
    async def loopqueue(self, ctx: commands.Context):
        queue = self.get_queue(ctx.guild.id)
        queue.loop_queue = not queue.loop_queue
        queue.loop = False

        status = "enabled 🔁" if queue.loop_queue else "disabled"
        await ctx.send(f"Queue loop {status}")

    @commands.hybrid_command(name="clear", description="Clear the queue")
    async def clear(self, ctx: commands.Context):
        queue = self.get_queue(ctx.guild.id)
        count = len(queue)
        queue.queue.clear()
        await ctx.send(f"🗑️ Cleared {count} songs from the queue")

    @commands.hybrid_command(name="shuffle", description="Shuffle the queue")
    async def shuffle(self, ctx: commands.Context):
        import random
        queue = self.get_queue(ctx.guild.id)

        if len(queue) < 2:
            return await ctx.send("❌ Not enough songs to shuffle!")

        songs = list(queue.queue)
        random.shuffle(songs)
        queue.queue = deque(songs)
        await ctx.send("🔀 Queue shuffled!")

    @commands.hybrid_command(name="remove", description="Remove a song from the queue")
    @app_commands.describe(position="Position of the song to remove")
    async def remove(self, ctx: commands.Context, position: int):
        queue = self.get_queue(ctx.guild.id)

        if position < 1 or position > len(queue):
            return await ctx.send(f"❌ Invalid position! Queue has {len(queue)} songs.")

        songs = list(queue.queue)
        removed = songs.pop(position - 1)
        queue.queue = deque(songs)

        await ctx.send(f"🗑️ Removed **{removed.title}** from the queue")

# ============== Bot Setup ==============
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    logger.info("=" * 50)
    logger.info(f"Bot logged in as {bot.user} (ID: {bot.user.id})")
    logger.info(f"Connected to {len(bot.guilds)} server(s): {[g.name for g in bot.guilds]}")
    logger.info("=" * 50)

    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} slash command(s)")
    except Exception as e:
        logger.error(f"Failed to sync commands: {e}", exc_info=True)

    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.listening,
        name="!help for commands"
    ))
    logger.info("Bot is ready!")


@bot.event
async def on_disconnect():
    logger.warning("Bot disconnected from Discord")


@bot.event
async def on_resumed():
    logger.info("Bot resumed connection to Discord")


@bot.event
async def on_voice_state_update(member, before, after):
    if member == bot.user:
        if before.channel and not after.channel:
            logger.warning(f"Bot was disconnected from voice channel: {before.channel.name} in {before.channel.guild.name}")
        elif not before.channel and after.channel:
            logger.info(f"Bot joined voice channel: {after.channel.name} in {after.channel.guild.name}")
        elif before.channel != after.channel:
            logger.info(f"Bot moved from {before.channel.name} to {after.channel.name}")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing argument: `{error.param.name}`")
    elif isinstance(error, commands.CommandNotFound):
        pass
    else:
        logger.error(f"Command error in '{ctx.command}' by {ctx.author}: {error}", exc_info=True)
        await ctx.send(f"❌ An error occurred: {error}")

async def main():
    async with bot:
        await bot.add_cog(Music(bot))
        logger.info("Music cog loaded")
        await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    logger.info("Discord Music Bot (Uta) starting...")
    try:
        asyncio.run(main())
    except discord.LoginFailure:
        logger.critical("Invalid Discord token! Check your DISCORD_TOKEN in .env")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.critical(f"Bot crashed: {e}", exc_info=True)
        sys.exit(1)