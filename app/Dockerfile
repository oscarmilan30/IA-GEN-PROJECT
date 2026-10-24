FROM python:3.12-slim

WORKDIR /app

# Instalar ODBC Driver 18 para Azure SQL
RUN apt-get update && apt-get install -y \
    curl gnupg unixodbc-dev \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /etc/apt/keyrings/microsoft.gpg \
    && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/microsoft.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y msodbcsql18 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copiar requirements e instalar
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar solo la app Streamlit
COPY App_NutriAgente.py .

EXPOSE 8501

CMD ["streamlit", "run", "App_NutriAgente.py", "--server.port=8501", "--server.address=0.0.0.0"]
