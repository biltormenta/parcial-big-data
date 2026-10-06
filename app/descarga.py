import glob
import os
import random

from app.config import DATOS_DIR, KAGGLE_DATASET, OBJETIVO_REGISTROS

BYTES_POR_FILA = 64  # una linea de un .plt pesa mas o menos esto


def descargar():
    # kagglehub usa la api de kaggle, el dataset es publico y no pide token
    # si hay KAGGLE_USERNAME/KAGGLE_KEY en el entorno (credencial de jenkins) los usa
    os.environ.setdefault("KAGGLEHUB_CACHE", os.path.join(DATOS_DIR, "kaggle"))
    for var in ("KAGGLE_USERNAME", "KAGGLE_KEY"):
        if not os.environ.get(var):
            os.environ.pop(var, None)
    import kagglehub
    ruta = kagglehub.dataset_download(KAGGLE_DATASET)
    print("dataset en", ruta)
    return ruta


def seleccionar_archivos(ruta, objetivo=OBJETIVO_REGISTROS, semilla=42):
    archivos = sorted(glob.glob(os.path.join(ruta, "**", "*.plt"), recursive=True))
    assert archivos, f"no encontre archivos .plt en {ruta}"
    # orden aleatorio fijo para que la muestra cubra varios usuarios y sea reproducible
    random.Random(semilla).shuffle(archivos)
    elegidos, filas = [], 0
    for a in archivos:
        elegidos.append(a)
        filas += max(os.path.getsize(a) // BYTES_POR_FILA - 6, 0)
        if filas >= objetivo:
            break
    print(f"{len(elegidos)} archivos de {len(archivos)} (~{filas} registros estimados)")
    return elegidos
