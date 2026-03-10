# https://developers.home-assistant.io/docs/add-ons/configuration#add-on-dockerfile
ARG BUILD_FROM
FROM $BUILD_FROM

# Install Python runtime deps via Alpine packages (pre-built, no compilation needed)
# then install aiohttp and aiosqlite from pip (no Alpine packages available)
RUN apk add --no-cache \
    python3 \
    py3-pip \
    py3-lxml \
    py3-requests \
    py3-dateutil \
    && pip3 install --no-cache-dir --break-system-packages \
    aiohttp \
    aiosqlite

# Copy root filesystem
COPY rootfs /
