import os
import re
import asyncio
import discord
from discord.ext import commands

import yt_dlp

# Minimal Flask server
from flask import Flask, request, jsonify
import threading

##################################################
#               DISCORD BOT SETUP
##################################################

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "REPLACE_ME")

intents = discord.Intents.default()
intents.message_content = True  # needed to read text messages
bot = commands.Bot(command_prefix="!", intents=intents)

# In-memory queue
# Each item is a dict with keys: url, title, requested_by
song_queue = []

# Track the current song
current_song_info = {
    "url": None,
    "title": None,
    "requested_by": None,
}

# We'll store user IDs in a list for easy iteration:
SPECIAL_USER_IDS = [
    139880416726220801,
    109138375927148544
]

FFMPEG_OPTIONS = {
    # reconnect logic; helpful for streams
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

##################################################
#          YT_DLP SEARCH OR URL HELPER
##################################################

def is_url(string: str) -> bool:
    """
    Quick check if the string looks like an http(s) URL.
    """
    pattern = r'^(?:http|ftp)s?://'  # matches http://, https://, ftp://, etc.
    return re.match(pattern, string, re.IGNORECASE) is not None

def yt_dlp_extract_info(query_or_url: str):
    """
    Uses yt_dlp to extract the best audio source.
    - If query_or_url is a valid URL, use it directly.
    - Otherwise, treat it as a YT search term (ytsearch1:<query>).
    Returns a dict containing 'url' and 'title'.
    """
    # If it's NOT an actual URL, perform a YouTube search
    if not is_url(query_or_url):
        query_or_url = f"ytsearch1:{query_or_url}"

    ytdlp_options = {
        'format': 'bestaudio/best',
        'quiet': True,
        'noplaylist': True,
        'ignoreerrors': True,
    }
    with yt_dlp.YoutubeDL(ytdlp_options) as ydl:
        info = ydl.extract_info(query_or_url, download=False)
        # If it's a search or playlist, info might contain 'entries'
        if 'entries' in info:
            info = (info['entries'] or [None])[0]
        if not info:
            raise ValueError("No video found for this query.")

    return {
        'title': info.get('title', 'Unknown Title'),
        'url': info['url'],
    }

##################################################
#               BOT EVENTS & COMMANDS
##################################################

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

@bot.command(name="play")
async def play_cmd(ctx, *, query: str):
    """
    !play <URL or search term>

    Using *query: str to capture full text (in case user typed multiple words).
    """
    # If bot is not in a VC, join the user's channel
    if not ctx.voice_client or not ctx.voice_client.is_connected():
        if ctx.author.voice:
            await ctx.author.voice.channel.connect()
        else:
            embed = discord.Embed(
                title="Error",
                description="You must be in a voice channel to play music.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return
    
    # Extract info (search or URL)
    try:
        info = yt_dlp_extract_info(query)
    except Exception as e:
        embed = discord.Embed(
            title="Error",
            description=f"Could not extract info from the input. Details: {e}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    song_queue.append({
        "url": info["url"],
        "title": info["title"],
        "requested_by": ctx.author.name
    })
    
    embed = discord.Embed(
        title="Added to Queue",
        description=f"**[{info['title']}]({query})**\nRequested by **{ctx.author.name}**",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed)

    # If nothing is currently playing, start playback immediately
    if not ctx.voice_client.is_playing():
        await handle_queue(ctx)

@bot.command(name="skip")
async def skip_cmd(ctx):
    """
    !skip - Skip the current song
    """
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()  # triggers _after_song -> handle_queue
        embed = discord.Embed(
            title="Skipping",
            description="Skipping current song.",
            color=discord.Color.orange()
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="Skip",
            description="No song is playing right now.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

@bot.command(name="queue")
async def show_queue_cmd(ctx):
    """
    !queue - Show the current queue of songs
    """
    if not song_queue:
        embed = discord.Embed(
            title="Queue",
            description="The queue is empty.",
            color=discord.Color.light_grey()
        )
        await ctx.send(embed=embed)
        return

    desc_lines = []
    for idx, song in enumerate(song_queue, start=1):
        desc_lines.append(f"{idx}. **{song['title']}** (requested by {song['requested_by']})")
    
    embed = discord.Embed(
        title="Current Queue",
        description="\n".join(desc_lines),
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed)

@bot.command(name="leave")
async def leave_cmd(ctx):
    """
    !leave - Bot leaves the voice channel
    """
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        embed = discord.Embed(
            title="Voice Disconnect",
            description="Disconnected from voice channel.",
            color=discord.Color.light_grey()
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="Error",
            description="I'm not in a voice channel.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

##################################################
#               PLAYBACK CONTROL
##################################################

async def handle_queue(ctx):
    """
    Handles playing the next song in the queue, if any.
    """
    if not song_queue:
        return

    next_song = song_queue.pop(0)
    current_song_info["url"] = next_song["url"]
    current_song_info["title"] = next_song["title"]
    current_song_info["requested_by"] = next_song["requested_by"]

    # We'll use FFmpegOpusAudio to play
    source = discord.FFmpegOpusAudio(next_song["url"], **FFMPEG_OPTIONS)
    ctx.voice_client.play(
        source,
        after=lambda e: asyncio.run_coroutine_threadsafe(_after_song(ctx), bot.loop)
    )

    embed = discord.Embed(
        title="Now Playing",
        description=f"**{next_song['title']}**\nRequested by **{next_song['requested_by']}**",
        color=discord.Color.green()
    )
    await ctx.send(embed=embed)

async def _after_song(ctx):
    """
    Callback after a song finishes.
    """
    # Clear current song
    current_song_info["url"] = None
    current_song_info["title"] = None
    current_song_info["requested_by"] = None

    # If there are still songs in the queue, play next
    if song_queue:
        await handle_queue(ctx)

##################################################
#                FLASK WEB SERVER
##################################################

app = Flask(__name__)

@app.route("/play", methods=["POST"])
def play_song_webhook():
    """
    Minimal endpoint to accept {"song": "..."} JSON and enqueue it.
    This replicates the logic of !play without needing a Discord text command.
    """
    data = request.get_json(silent=True) or {}
    song = data.get("song")
    if not song:
        return jsonify({"error": "No 'song' provided"}), 400

    # We'll schedule an async function on the bot loop that:
    # 1) Joins a voice channel if not already in one (looking for special user IDs).
    # 2) Enqueues the song.
    # 3) Plays if nothing else is playing.
    future = asyncio.run_coroutine_threadsafe(_web_enqueued_play(song), bot.loop)

    return jsonify({"status": "ok", "message": f"Enqueued: {song}"}), 200

TEXT_CHANNEL_ID = 712276849006477362

async def _web_enqueued_play(song_url: str):
    # 1) Attempt to join a voice channel if the bot isn't in one
    #    Specifically, look for the 2 user IDs in any of the bot's guilds.
    voice_client = None

    # Check if we're already in a voice channel
    for vc in bot.voice_clients:
        if vc.guild and vc.is_connected():
            voice_client = vc
            break

    # If not already in a channel, look for a special user's channel
    if not voice_client:
        # Try each guild in which the bot is a member
        found_channel = False
        for guild in bot.guilds:
            if found_channel:
                break

            # Check if user1 or user2 is in a voice channel
            for user_id in SPECIAL_USER_IDS:
                member = guild.get_member(user_id)
                if member and member.voice and member.voice.channel:
                    # Found a user in a voice channel; join that channel
                    voice_client = await member.voice.channel.connect()
                    found_channel = True
                    break

        # If we still don't have a voice_client, fallback to first voice channel in first guild
        if not found_channel:
            if bot.guilds:
                guild = bot.guilds[0]
                voice_channels = [ch for ch in guild.channels if ch.type == discord.ChannelType.voice]
                if voice_channels:
                    voice_client = await voice_channels[0].connect()

    # 2) Extract info & enqueue
    try:
        info = yt_dlp_extract_info(song_url)
    except Exception as e:
        print(f"[ERROR] Could not extract info from {song_url}. Exception: {e}")
        return

    requested_by = "Webhook"
    song_queue.append({
        "url": info["url"],
        "title": info["title"],
        "requested_by": requested_by
    })

    # 2a) POST A MESSAGE to the text channel:
    channel = bot.get_channel(TEXT_CHANNEL_ID)
    if channel is not None:
        await channel.send(
            f"**Added to Queue**: {info['title']}\n"
            f"Requested by: {requested_by}"
        )
    else:
        print(f"[WARNING] Could not find text channel {TEXT_CHANNEL_ID}")

    # 3) If not currently playing, start playback
    if voice_client and not voice_client.is_playing():
        # Create a "dummy context"
        class DummyCtx:
            def __init__(self, vc):
                self.voice_client = vc
                self.guild = vc.guild

            async def send(self, *args, **kwargs):
                # If we want to post updates to the same text channel, do so:
                if channel is not None:
                    await channel.send(*args, **kwargs)
                else:
                    print("[INFO] BOT MSG (no text channel found):", args, kwargs)

        dummy_ctx = DummyCtx(voice_client)
        await handle_queue(dummy_ctx)

def run_flask_app():
    app.run(host="0.0.0.0", port=8008)

##################################################
#       RUN THE BOT + FLASK (CONCURRENT)
##################################################

if __name__ == "__main__":
    # Start Flask in a separate thread
    flask_thread = threading.Thread(target=run_flask_app, daemon=True)
    flask_thread.start()

    # Start the Discord bot (blocking call)
    bot.run(DISCORD_BOT_TOKEN)
