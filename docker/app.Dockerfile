# Imagen única para la API, los workers de Dask, la ingesta y las pruebas
FROM python:3.11-slim

WORKDIR /srv
# Primero solo requirements.txt: Docker reutiliza esta capa (caché) mientras no cambien las dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código y pruebas dentro de la imagen (por eso Jenkins puede correr pytest dentro de ella)
COPY app ./app
COPY tests ./tests

# /data es el volumen compartido; permisos abiertos para que cualquier servicio escriba
RUN mkdir -p /data && chmod 777 /data
# PYTHONPATH permite hacer "from app import ..." desde cualquier carpeta
ENV PYTHONPATH=/srv
EXPOSE 5000
# Por defecto arranca la API con gunicorn (2 procesos); Dask e ingesta sobrescriben este comando en el compose
CMD ["gunicorn", "-b", "0.0.0.0:5000", "-w", "2", "app.api:app"]
