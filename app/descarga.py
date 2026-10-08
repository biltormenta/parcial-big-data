import glob
import os
import random

from app.config import DATOS_DIR, KAGGLE_DATASET, OBJETIVO_REGISTROS

BYTES_POR_FILA = 64  # una línea de un .plt pesa más o menos esto (sirve para estimar filas sin leer el archivo)


def descargar():
    """Descarga el dataset de Kaggle con su API (kagglehub) y devuelve la carpeta donde quedó."""
    # kagglehub usa la API de Kaggle; este dataset es público y no pide token.
    # Si hay KAGGLE_USERNAME/KAGGLE_KEY en el entorno (credencial de Jenkins) los usa.
    # La caché se guarda en el volumen compartido para no volver a bajar 337 MB cada vez.
    os.environ.setdefault("KAGGLEHUB_CACHE", os.path.join(DATOS_DIR, "kaggle"))
    # Si las variables existen pero vienen vacías (docker-compose las pasa vacías), kagglehub
    # intentaría autenticarse con un usuario en blanco y fallaría: por eso se eliminan.
    for var in ("KAGGLE_USERNAME", "KAGGLE_KEY"):
        if not os.environ.get(var):
            os.environ.pop(var, None)
    import kagglehub  # se importa aquí para que las variables de arriba ya estén listas
    ruta = kagglehub.dataset_download(KAGGLE_DATASET)
    print("dataset en", ruta)
    return ruta


def seleccionar_archivos(ruta, objetivo=OBJETIVO_REGISTROS, semilla=42):
    """Elige archivos .plt al azar (pero siempre los mismos) hasta juntar ~`objetivo` registros."""
    archivos = sorted(glob.glob(os.path.join(ruta, "**", "*.plt"), recursive=True))
    assert archivos, f"no encontre archivos .plt en {ruta}"
    # Orden aleatorio con semilla fija: la muestra cubre varios usuarios (no solo los primeros)
    # y es reproducible, porque en cada corrida salen los mismos archivos.
    random.Random(semilla).shuffle(archivos)
    elegidos, filas = [], 0
    for a in archivos:
        elegidos.append(a)
        # filas estimadas = tamaño / bytes por línea - 6 líneas de encabezado de cada .plt
        filas += max(os.path.getsize(a) // BYTES_POR_FILA - 6, 0)
        if filas >= objetivo:
            break
    print(f"{len(elegidos)} archivos de {len(archivos)} (~{filas} registros estimados)")
    return elegidos
