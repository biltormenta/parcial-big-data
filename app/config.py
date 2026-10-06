import os

# todo se configura por variables de entorno, con valores por defecto para docker compose
MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongo:27017")
MONGO_DB = os.getenv("MONGO_DB", "geolife")
COLECCION_PUNTOS = "puntos"

DASK_SCHEDULER = os.getenv("DASK_SCHEDULER", "tcp://dask-scheduler:8786")

DATOS_DIR = os.getenv("DATOS_DIR", "/data")
KAGGLE_DATASET = "arashnic/microsoft-geolife-gps-trajectory-dataset"

# el dataset completo tiene ~25M de puntos; se trabaja con una muestra (minimo 1M exigido)
OBJETIVO_REGISTROS = int(os.getenv("OBJETIVO_REGISTROS", "2000000"))
TAM_LOTE_MONGO = int(os.getenv("TAM_LOTE_MONGO", "10000"))

# geolife guarda la hora en GMT, pekin es GMT+8
OFFSET_LOCAL_HORAS = 8
