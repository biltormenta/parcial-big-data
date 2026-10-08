import json
import os
import time

import dask.dataframe as dd
import pandas as pd
from distributed import Client
from pymongo import GEOSPHERE, MongoClient

from app import config
from app.descarga import descargar, seleccionar_archivos
from app.limpieza import COLUMNAS_PLT, META_LIMPIO, a_geojson, estadisticas, limpiar

# Estructura esperada del resultado de estadisticas(), para que Dask no tenga que adivinarla
META_STATS = pd.DataFrame({"leidos": pd.Series(dtype="int64"), "nulos": pd.Series(dtype="int64"),
                           "fuera_rango": pd.Series(dtype="int64"), "sin_fecha": pd.Series(dtype="int64")})


def cargar_lote(df, uri, db, coleccion, tam_lote):
    """Inserta una partición en Mongo, en lotes de `tam_lote` documentos. Corre dentro de un worker de Dask."""
    # Esto corre dentro de cada worker de Dask: cada uno abre su propia conexión a Mongo,
    # así la carga se reparte entre los 2 workers en vez de pasar toda por un solo proceso.
    docs = a_geojson(df)
    col = MongoClient(uri)[db][coleccion]
    for i in range(0, len(docs), tam_lote):
        # ordered=False: si un documento falla, Mongo sigue con los demás del lote
        col.insert_many(docs[i:i + tam_lote], ordered=False)
    return pd.DataFrame({"n": [len(docs)]})


def main():
    """Flujo completo: descargar -> limpiar con Dask -> guardar Parquet -> cargar a Mongo -> crear índices."""
    t0 = time.time()
    ruta = descargar()
    archivos = seleccionar_archivos(ruta)

    # Se conecta al scheduler del clúster de Dask (el contenedor dask-scheduler)
    client = Client(config.DASK_SCHEDULER)
    print("dask:", client.dashboard_link, "workers:", len(client.scheduler_info()["workers"]))

    # Lectura particionada: un archivo .plt = una partición (blocksize=None), así cada archivo
    # lo procesa un worker. Las 6 primeras líneas de cada .plt son encabezado y se saltan.
    # Todo se lee como texto (dtype=str) y la limpieza convierte los tipos después.
    # include_path_column agrega la ruta de cada archivo, de ahí se saca el usuario.
    crudo = dd.read_csv(archivos, skiprows=6, header=None,
                        names=["lat", "lon", "c0", "alt_ft", "c1", "fecha", "hora"],
                        usecols=["lat", "lon", "alt_ft", "fecha", "hora"],
                        include_path_column="ruta", blocksize=None, dtype=str)
    crudo["ruta"] = crudo["ruta"].astype(str)

    # Paso 1: contar cuántos registros se descartarán y por qué (para el informe)
    stats = crudo.map_partitions(estadisticas, meta=META_STATS).compute().sum()
    # Paso 2: aplicar la limpieza (esto es perezoso: no corre hasta que se escribe el Parquet)
    limpio = crudo.map_partitions(limpiar, meta=META_LIMPIO)
    # Se reparte en 8 particiones por worker para que la carga a Mongo quede pareja
    limpio = limpio.repartition(npartitions=max(len(client.scheduler_info()["workers"]) * 8, 8))

    # Se guarda el Parquet limpio: lo usan después los benchmarks de Dask y de Spark
    destino = os.path.join(config.DATOS_DIR, "clean", "puntos")
    # Spark no lee timestamps en nanosegundos (el formato por defecto de pandas), por eso se
    # guardan en microsegundos. Sin esto Spark fallaba al leer el Parquet.
    limpio.to_parquet(destino, overwrite=True, write_index=False,
                      coerce_timestamps="us", allow_truncated_timestamps=True)
    print("parquet limpio en", destino)

    # Carga a Mongo por lotes, de nuevo desde los workers. Se borra la colección antes
    # para que repetir la ingesta no duplique los datos.
    col = MongoClient(config.MONGO_URI)[config.MONGO_DB][config.COLECCION_PUNTOS]
    col.drop()
    cargado = dd.read_parquet(destino).map_partitions(
        cargar_lote, config.MONGO_URI, config.MONGO_DB, config.COLECCION_PUNTOS,
        config.TAM_LOTE_MONGO, meta={"n": "int64"}).compute()
    total = int(cargado["n"].sum())

    # Los índices se crean al final: cargar con el índice 2dsphere ya creado es mucho más lento.
    # 2dsphere es el que hace posibles $near, $geoWithin y $geoNear; el de ts acelera filtros por fecha.
    col.create_index([("loc", GEOSPHERE)])
    col.create_index("ts")
    en_mongo = col.count_documents({})

    resumen = {
        "archivos": len(archivos),
        "leidos": int(stats["leidos"]),
        "descartados_nulos": int(stats["nulos"]),
        "descartados_fuera_rango": int(stats["fuera_rango"]),
        "descartados_fecha_invalida": int(stats["sin_fecha"]),
        # los duplicados no se cuentan al leer: son lo que sobra de restar todo lo demás
        "descartados_duplicados": int(stats["leidos"] - stats["nulos"] - stats["fuera_rango"]
                                      - stats["sin_fecha"] - total),
        "cargados_en_mongo": en_mongo,
        "segundos": round(time.time() - t0, 1),
    }
    # Verificaciones: lo que Mongo tiene debe coincidir con lo que se envió, y cumplir el mínimo del taller
    assert en_mongo == total, f"mongo tiene {en_mongo} y se enviaron {total}"
    assert en_mongo >= 1_000_000, "el taller pide al menos un millon de registros"
    with open(os.path.join(config.DATOS_DIR, "resumen_ingesta.json"), "w") as f:
        json.dump(resumen, f, indent=2)
    print(json.dumps(resumen, indent=2))


if __name__ == "__main__":
    main()
