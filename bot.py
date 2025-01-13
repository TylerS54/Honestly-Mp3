import os
import asyncio
import discord
from discord.ext import commands

# Voice support
import yt_dlp
from discord import FFmpegPCMAudio

# Web server
from flask import Flask, render_template_string
import threading

##################################################
#               DISCORD BOT SETUP
##################################################

# For local testing, you can store your bot token as an environment variable:
# export DISCORD_BOT_TOKEN="YOUR_TOKEN_HERE"
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "REPLACE_ME")

intents = discord.Intents.default()
intents.message_content = True  # needed to read messages in guild
bot = commands.Bot(command_prefix="!", intents=intents)

# In-memory queue
song_queue = []

# Simple container to keep track of what's currently playing
current_song_info = {
    "url": None,
    "title": None,
    "requested_by": None,
}

# Ensure FFmpeg is installed in the container/host where you run the bot.
FFMPEG_OPTIONS = {
    'before_options': '-nostdin',
    'options': '-vn'
}

# --------------
# YT-DLP Helper
# --------------
def yt_dlp_extract_info(url: str):
    """
    Uses yt_dlp to extract the best audio source.
    Returns a dict containing the 'url' and 'title' keys if successful.
    """
    ytdlp_options = {
        'format': 'bestaudio/best',
        'quiet': True,
        'noplaylist': True,
        'ignoreerrors': True,
    }
    with yt_dlp.YoutubeDL(ytdlp_options) as ydl:
        info = ydl.extract_info(url, download=False)
    return {
        'title': info.get('title', 'Unknown Title'),
        'url': info['url'],
    }

# --------------
# Bot Commands
# --------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

@bot.command(name="join")
async def join(ctx):
    """
    Joins the voice channel of the user issuing the command.
    """
    if ctx.author.voice:
        channel = ctx.author.voice.channel
        await channel.connect()
        await ctx.send(f"Joined {channel}")
    else:
        await ctx.send("You need to be in a voice channel first.")

@bot.command(name="leave")
async def leave(ctx):
    """
    Leaves the voice channel.
    """
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("Disconnected from voice channel.")
    else:
        await ctx.send("I'm not in a voice channel.")

@bot.command(name="play")
async def play(ctx, url: str):
    """
    Play the given YouTube URL or add it to the queue.
    """
    # Extract audio info
    try:
        info = yt_dlp_extract_info(url)
    except Exception as e:
        await ctx.send(f"Error extracting info: {e}")
        return
    
    # Add to queue
    song_queue.append({
        "url": info["url"],
        "title": info["title"],
        "requested_by": ctx.author.name
    })
    await ctx.send(f"Added **{info['title']}** to the queue!")

    # Attempt to play if not already playing
    if not ctx.voice_client.is_playing():
        await handle_queue(ctx)

async def handle_queue(ctx):
    """
    Handles playing the next song in the queue.
    """
    if not song_queue:
        # Queue is empty
        return

    # Get the next song
    next_song = song_queue.pop(0)
    
    # Update current song info
    current_song_info["url"] = next_song["url"]
    current_song_info["title"] = next_song["title"]
    current_song_info["requested_by"] = next_song["requested_by"]

    # Create source
    source = FFmpegPCMAudio(next_song["url"], **FFMPEG_OPTIONS)
    ctx.voice_client.play(
        source,
        after=lambda e: asyncio.run_coroutine_threadsafe(_after_song(ctx), bot.loop)
    )
    await ctx.send(f"Now playing **{next_song['title']}** requested by {next_song['requested_by']}.")

async def _after_song(ctx):
    """
    Callback after a song finishes.
    """
    # Reset current playing if needed
    current_song_info["url"] = None
    current_song_info["title"] = None
    current_song_info["requested_by"] = None
    
    # If there are still songs in the queue, play the next one
    if song_queue:
        await handle_queue(ctx)

@bot.command(name="queue")
async def show_queue(ctx):
    """
    Shows the current queue of songs.
    """
    if not song_queue:
        await ctx.send("The queue is empty.")
        return

    message_lines = ["**Current Queue:**"]
    for idx, song in enumerate(song_queue, start=1):
        message_lines.append(f"{idx}. {song['title']} (requested by {song['requested_by']})")
    await ctx.send("\n".join(message_lines))

##################################################
#                FLASK WEB SERVER
##################################################

app = Flask(__name__)

# A simple HTML template to display queue
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Discord Music Bot Queue</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        h1, h2 { margin-bottom: 0.5em; }
        ul { list-style: none; padding: 0; }
        li { margin: 0.2em 0; }
        .current-song {
            margin: 1em 0;
            padding: 1em;
            background-color: #f3f3f3;
        }
    </style>
</head>
<body>
    <h1>Discord Music Bot</h1>
    {% if current.title %}
    <div class="current-song">
      <h2>Currently Playing</h2>
      <p><strong>Title:</strong> {{ current.title }}</p>
      <p><strong>Requested by:</strong> {{ current.requested_by }}</p>
    </div>
    {% else %}
      <p>No song is currently playing.</p>
    {% endif %}
    
    <h2>Upcoming Queue</h2>
    {% if queue %}
      <ul>
        {% for song in queue %}
        <li><strong>{{ song.title }}</strong> (requested by {{ song.requested_by }})</li>
        {% endfor %}
      </ul>
    {% else %}
      <p>The queue is empty.</p>
    {% endif %}
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(
        HTML_TEMPLATE,
        current=current_song_info,
        queue=song_queue
    )

def run_flask_app():
    # You can change host/port if desired
    app.run(host="0.0.0.0", port=8080)

##################################################
#       RUN THE BOT + FLASK (CONCURRENT)
##################################################

if __name__ == "__main__":
    # Run Flask in a separate thread
    flask_thread = threading.Thread(target=run_flask_app, daemon=True)
    flask_thread.start()
    
    # Run Discord bot (blocking call)
    bot.run(DISCORD_BOT_TOKEN)
