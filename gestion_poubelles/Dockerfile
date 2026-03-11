ARG BUILD_FROM
FROM ${BUILD_FROM}

# Install Python and system dependencies
RUN apk add --no-cache \
    python3 \
    py3-pip \
    tesseract-ocr \
    tesseract-ocr-data-fra \
    poppler-utils \
    bash \
    jq \
    curl

# Install Python packages
RUN pip3 install --no-cache-dir --break-system-packages \
    flask \
    pytesseract \
    pdf2image \
    Pillow \
    requests \
    python-dateutil \
    apscheduler \
    werkzeug \
    pyyaml

# Copy application
COPY rootfs /
COPY run.sh /

# Make run script executable
RUN chmod a+x /run.sh

WORKDIR /opt/poubelles

CMD [ "/run.sh" ]
