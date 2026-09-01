FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc curl ca-certificates\
    && rm -rf /var/lib/apt/lists/*

# Download the latest installer
ADD https://astral.sh/uv/install.sh /uv-installer.sh

# Run the installer then remove it
RUN sh /uv-installer.sh && rm /uv-installer.sh

# Ensure the installed binary is on the `PATH`
ENV PATH="/root/.local/bin/:$PATH"

COPY app/ ./app/
COPY main.py .
COPY CHANGELOG.md .
COPY pyproject.toml .
COPY uv.lock .

RUN uv sync --locked

ENTRYPOINT ["uv", "run", "main.py"]
