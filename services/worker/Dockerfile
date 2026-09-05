FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
        fonts-liberation \
        libasound2 \
        libatk-bridge2.0-0 \
        libatk1.0-0 \
        libcairo2 \
        libcups2 \
        libdbus-1-3 \
        libdrm2 \
        libgbm1 \
        libglib2.0-0 \
        libgtk-3-0 \
        libnspr4 \
        libnss3 \
        libpango-1.0-0 \
        libu2f-udev \
        libvulkan1 \
        libx11-6 \
        libxcb1 \
        libxcomposite1 \
        libxdamage1 \
        libxext6 \
        libxfixes3 \
        libxkbcommon0 \
        libxrandr2 \
        wget \
        xdg-utils \
        xvfb \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /etc/apt/keyrings/google-linux.gpg \
    && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-linux.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

COPY services/worker/pyproject.toml ./
COPY services/worker/app ./app

RUN echo "BUILD MARKER: services/worker/Dockerfile fbref-no-cache interval-7.5"
RUN pip install --no-cache-dir .

RUN seleniumbase install chromedriver

RUN useradd --create-home --uid 1000 --shell /bin/bash appuser \
    && mkdir -p /home/appuser/.cache /home/appuser/.config /home/appuser/Downloads /tmp/fbref-debug \
    && chown -R appuser:appuser /home/appuser /tmp/fbref-debug /app /usr/local/lib/python3.12/site-packages/seleniumbase/drivers

USER appuser

ENV HOME=/home/appuser

CMD ["stockball-worker", "worker"]
