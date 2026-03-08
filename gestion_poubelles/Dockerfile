ARG BUILD_FROM
FROM ${BUILD_FROM}

# Install Python and system dependencies
RUN apk add --no-cache \
    python3 \
    py3-pip \
    tesseract-ocr \
    tesseract-ocr-data-fra \
    poppler-utils

# Install Python packages
RUN pip3 install --no-cache-dir --break-system-packages \
    flask \
    pytesseract \
    pdf2image \
    Pillow \
    requests \
    python-dateutil \
    apscheduler \
    werkzeug

# Copy application
COPY rootfs /

# Make S6 service scripts executable
RUN chmod a+x /etc/s6-overlay/s6-rc.d/poubelles/run

WORKDIR /opt/poubelles
