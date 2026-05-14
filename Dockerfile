FROM python:3.12-slim

WORKDIR /app

# Dependências do sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Instala dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o código
COPY . .

# Cria diretório para DB local efêmero
RUN mkdir -p /tmp/bolao

# Variáveis de ambiente padrão (sobrescritas pelo .env ou Render)
ENV HOST=0.0.0.0
ENV PORT=8000
ENV LOCAL_DB_PATH=/tmp/bolao/local.db

EXPOSE 8000

CMD ["python", "main.py"]
