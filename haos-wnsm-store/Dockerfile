# https://developers.home-assistant.io/docs/add-ons/configuration#add-on-dockerfile
ARG BUILD_FROM
FROM $BUILD_FROM

# Install Python runtime and lxml build dependencies
RUN apk add --no-cache \
    python3 \
    py3-pip \
    libxml2 \
    libxslt \
    && apk add --no-cache --virtual .build-deps \
    gcc \
    musl-dev \
    python3-dev \
    libxml2-dev \
    libxslt-dev \
    && pip3 install --no-cache-dir \
    aiohttp \
    aiosqlite \
    requests \
    python-dateutil \
    lxml \
    && apk del .build-deps

# Copy root filesystem
COPY rootfs /
