import os
import asyncio
import discord
from discord.ext import commands

# Voice support
import yt_dlp
from discord import FFmpegPCMAudio

# Web server
from flask import Flask, request, render_template_string, redirect, url_for
import threading

##################################################
#               DISCORD BOT SETUP
##################################################

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "REPLACE_ME")

intents = discord.Intents.default()
intents.message_content = True  # needed to read messages in guild
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

FFMPEG_OPTIONS = {
    'before_options': '-nostdin',
    'options': '-vn'
}

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

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

##################################################
#               BOT COMMANDS
##################################################

@bot.command(name="play")
async def play(ctx, url: str):
    """
    Play the given YouTube URL or add it to the queue.
    If the bot is not in a voice channel, join the user's channel automatically.
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
    
    # Extract info
    try:
        info = yt_dlp_extract_info(url)
    except Exception as e:
        embed = discord.Embed(
            title="Error",
            description=f"Could not extract info from the URL. Details: {e}",
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
        description=f"**[{info['title']}]({url})**\nRequested by **{ctx.author.name}**",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed)

    # If not playing anything, handle immediately
    if not ctx.voice_client.is_playing():
        await handle_queue(ctx)

@bot.command(name="skip")
async def skip(ctx):
    """
    Skip the current song and move on to the next.
    """
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()  # This triggers _after_song and goes to the next in queue
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
async def show_queue(ctx):
    """
    Shows the current queue of songs.
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
async def leave(ctx):
    """
    Leaves the voice channel.
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

    source = FFmpegPCMAudio(next_song["url"], **FFMPEG_OPTIONS)
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

    # If there are still songs in queue, play next
    if song_queue:
        await handle_queue(ctx)

##################################################
#                FLASK WEB SERVER
##################################################

app = Flask(__name__)

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
        .controls form {
            display: inline-block;
            margin-left: 5px;
        }
        .controls button {
            padding: 4px 8px;
            margin: 2px;
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
        <div class="controls">
          <form action="{{ url_for('skip_song') }}" method="POST">
            <button type="submit">Skip</button>
          </form>
        </div>
      </div>
    {% else %}
      <p>No song is currently playing.</p>
    {% endif %}
    
    <h2>Upcoming Queue</h2>
    {% if queue %}
      <ul>
        {% for song in queue %}
          <li>
            <strong>{{ song.title }}</strong> (requested by {{ song.requested_by }})
            <div class="controls">
              <!-- Move Up -->
              {% if loop.index0 > 0 %}
                <form action="{{ url_for('move_song') }}" method="POST" style="display:inline;">
                  <input type="hidden" name="index" value="{{ loop.index0 }}">
                  <input type="hidden" name="direction" value="up">
                  <button type="submit">Up</button>
                </form>
              {% endif %}
              
              <!-- Move Down -->
              {% if loop.index0 < (queue|length - 1) %}
                <form action="{{ url_for('move_song') }}" method="POST" style="display:inline;">
                  <input type="hidden" name="index" value="{{ loop.index0 }}">
                  <input type="hidden" name="direction" value="down">
                  <button type="submit">Down</button>
                </form>
              {% endif %}
              
              <!-- Remove from queue -->
              <form action="{{ url_for('remove_song') }}" method="POST" style="display:inline;">
                <input type="hidden" name="index" value="{{ loop.index0 }}">
                <button type="submit">Remove</button>
              </form>
            </div>
          </li>
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

@app.route("/skip", methods=["POST"])
def skip_song():
    # Skip current song
    coro = skip_current_song()
    asyncio.run_coroutine_threadsafe(coro, bot.loop)
    return redirect(url_for("index"))

async def skip_current_song():
    # Attempt to skip in the first connected voice client
    for vc in bot.voice_clients:
        if vc.is_playing():
            vc.stop()
    return

@app.route("/move", methods=["POST"])
def move_song():
    index = int(request.form.get("index", -1))
    direction = request.form.get("direction")

    if 0 <= index < len(song_queue):
        if direction == "up" and index > 0:
            song_queue[index - 1], song_queue[index] = song_queue[index], song_queue[index - 1]
        elif direction == "down" and index < len(song_queue) - 1:
            song_queue[index + 1], song_queue[index] = song_queue[index], song_queue[index + 1]

    return redirect(url_for("index"))

@app.route("/remove", methods=["POST"])
def remove_song():
    index = int(request.form.get("index", -1))
    if 0 <= index < len(song_queue):
        song_queue.pop(index)
    return redirect(url_for("index"))

def run_flask_app():
    app.run(host="0.0.0.0", port=8080)

##################################################
#       RUN THE BOT + FLASK (CONCURRENT)
##################################################

if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask_app, daemon=True)
    flask_thread.start()
    bot.run('DISCORD_BOT_TOKEN')
