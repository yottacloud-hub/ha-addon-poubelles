ARG BUILD_FROM
FROM ${BUILD_FROM}

# Install Python and system dependencies
RUN apk add --no-cache \
    python3 \
    py3-pip \
    py3-pillow \
    py3-numpy \
    tesseract-ocr \
    tesseract-ocr-data-fra \
    poppler-utils

# Install Python packages
RUN pip3 install --no-cache-dir --break-system-packages \
    flask==3.0.0 \
    pytesseract==0.3.10 \
    pdf2image==1.17.0 \
    Pillow==10.2.0 \
    requests==2.31.0 \
    python-dateutil==2.9.0 \
    apscheduler==3.10.4 \
    werkzeug==3.0.1

# Copy application
COPY rootfs /

# Make S6 service scripts executable
RUN chmod a+x /etc/s6-overlay/s6-rc.d/poubelles/run

WORKDIR /opt/poubelles
