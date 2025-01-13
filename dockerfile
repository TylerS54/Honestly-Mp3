# Use a lightweight Python base image
FROM python:3.10-slim

# Install ffmpeg and libopus
RUN apt-get update && apt-get install -y ffmpeg libopus0 && rm -rf /var/lib/apt/lists/*

# Copy requirements.txt and install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your bot code
COPY bot.py .

# Expose the Flask port
EXPOSE 8008

# Set environment variable for your Discord bot token
# You can override this in Portainer or at runtime
ENV DISCORD_BOT_TOKEN="REPLACE"

# Run the bot
CMD [ "python", "bot.py" ]
