# Use python:3.10-slim-bullseye instead of python:3.10-slim
FROM python:3.10-slim-bullseye

# Install ffmpeg and libopus
RUN apt-get update \
    && apt-get install -y ffmpeg libopus0 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your bot code
COPY bot.py .

# Expose Flask port
EXPOSE 8008

# Environment variable for your Discord bot token
ENV DISCORD_BOT_TOKEN="REPLACE_ME"

# Run the bot
CMD [ "python", "bot.py" ]
