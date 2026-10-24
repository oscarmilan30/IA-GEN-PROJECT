FROM python:3.12-slim

WORKDIR /app

# Instalar dependencias del sistema para pyodbc (Azure SQL)
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    unixodbc-dev \
    && curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - \
    && curl https://packages.microsoft.com/config/debian/12/prod.list > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y msodbcsql18 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copiar requirements e instalar
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código
COPY Nutriagente.py .
COPY mcp_nutriagente_server.py .

# Copiar archivos de conocimiento
COPY Base_Conocimiento/ /app/Base_Conocimiento/
COPY Fuentes/ /app/Fuentes/

# Variables de entorno para rutas en Linux
ENV CARPETA_BDC=/app/Base_Conocimiento
ENV CARPETA_FUENTES=/app/Fuentes
ENV CARPETA_IDX=/app/Base_Conocimiento/indice_platos

EXPOSE 8081

CMD ["python", "mcp_nutriagente_server.py"]
