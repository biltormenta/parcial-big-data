import os

# Toda la configuración sale de variables de entorno (las define docker-compose.yml).
# Los valores por defecto son los nombres de servicio de la red de Docker Compose,
# por eso "mongo" y "dask-scheduler" funcionan como hostname dentro de los contenedores.
MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongo:27017")
MONGO_DB = os.getenv("MONGO_DB", "geolife")
COLECCION_PUNTOS = "puntos"  # colección con un documento GeoJSON por cada punto GPS

# Dirección del scheduler de Dask, que reparte el trabajo entre los 2 workers
DASK_SCHEDULER = os.getenv("DASK_SCHEDULER", "tcp://dask-scheduler:8786")

# Carpeta compartida (volumen "datos") donde quedan el dataset bajado y el Parquet limpio
DATOS_DIR = os.getenv("DATOS_DIR", "/data")
KAGGLE_DATASET = "arashnic/microsoft-geolife-gps-trajectory-dataset"

# El dataset completo tiene ~25M de puntos; se trabaja con una muestra (mínimo 1M exigido por el taller)
OBJETIVO_REGISTROS = int(os.getenv("OBJETIVO_REGISTROS", "2000000"))
# Cuántos documentos se insertan por cada insert_many (lotes de 10.000, como pide el taller)
TAM_LOTE_MONGO = int(os.getenv("TAM_LOTE_MONGO", "10000"))

# Geolife guarda la hora en GMT y Pekín es GMT+8; se usa para calcular hora/día/mes locales
OFFSET_LOCAL_HORAS = 8
