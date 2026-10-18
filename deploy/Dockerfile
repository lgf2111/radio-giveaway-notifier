# hotline -- 987FM giveaway notifier, with the optional audio pipeline.
#
# ARM64-friendly image for Oracle Cloud Always-Free Ampere A1 (also builds on
# amd64). ffmpeg is installed as a SYSTEM package (it is NOT a pip dependency);
# the Python project is installed with the [audio] extra so faster-whisper is
# available for on-device transcription.
#
# Build (on an ARM64 host or with buildx):
#   docker build -t hotline -f deploy/Dockerfile .
#
# Run (outbound-only; mounts your config + a persistent dedupe db):
#   docker run -d --name hotline --restart unless-stopped \
#     --env-file /etc/hotline/hotline.env \
#     -v /etc/hotline/config.toml:/etc/hotline/config.toml:ro \
#     -v hotline-data:/data \
#     hotline watch --config /etc/hotline/config.toml --db /data/hotline.db

FROM python:3.13-slim

# ffmpeg is a system dependency used to pull and clip the live stream.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Run as a dedicated non-root user.
RUN useradd --create-home --uid 10001 hotline

WORKDIR /app

# Copy the project and install it with the optional audio extra.
COPY . /app
RUN pip install --no-cache-dir ".[audio]"

USER hotline

# watch is the long-running, event-driven mode. Pass extra args
# (e.g. --config, --db) after the image name at `docker run` time.
ENTRYPOINT ["python", "-m", "hotline", "watch"]
