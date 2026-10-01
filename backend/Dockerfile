FROM python:3.11-slim

WORKDIR /app

# Instalar dependências de sistema necessárias para Bluetooth e DBus
RUN apt-get update && apt-get install -y --no-install-recommends \
    bluez \
    libbluetooth-dev \
    pkg-config \
    gcc \
    dbus \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
