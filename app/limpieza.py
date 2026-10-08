import pandas as pd

from app.config import OFFSET_LOCAL_HORAS

COLUMNAS_PLT = ["lat", "lon", "alt_ft", "fecha", "hora"]

# "meta" le dice a Dask qué columnas y tipos devuelve limpiar() sin tener que ejecutarla primero
META_LIMPIO = pd.DataFrame({
    "usuario": pd.Series(dtype="int32"),
    "trayectoria": pd.Series(dtype="object"),
    "ts": pd.Series(dtype="datetime64[ns]"),
    "lat": pd.Series(dtype="float64"),
    "lon": pd.Series(dtype="float64"),
    "alt_m": pd.Series(dtype="float64"),
})


def estadisticas(df):
    """Cuenta cuántos registros se van a descartar y por qué (devuelve una fila por partición)."""
    # errors="coerce" convierte lo que no sea número en NaN en vez de lanzar error
    lat = pd.to_numeric(df["lat"], errors="coerce")
    lon = pd.to_numeric(df["lon"], errors="coerce")
    nulos = lat.isna() | lon.isna()
    # "fuera de rango" solo cuenta los que no eran nulos, para que cada registro entre en una sola categoría
    fuera = ~nulos & ~(lat.between(-90, 90) & lon.between(-180, 180))
    ts = pd.to_datetime(df["fecha"].astype(str) + " " + df["hora"].astype(str), errors="coerce")
    sin_fecha = ~nulos & ~fuera & ts.isna()
    return pd.DataFrame({
        "leidos": [len(df)],
        "nulos": [int(nulos.sum())],
        "fuera_rango": [int(fuera.sum())],
        "sin_fecha": [int(sin_fecha.sum())],
    })


def limpiar(df):
    """Aplica las 4 reglas de limpieza a una partición (un archivo .plt) y deja las columnas finales."""
    df = df.copy()
    # el CSV se leyó todo como texto (dtype=str) para que un valor raro no rompa la lectura
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df["alt_ft"] = pd.to_numeric(df["alt_ft"], errors="coerce")

    # 1. coordenadas nulas: un punto sin posición no se puede indexar como GeoJSON
    df = df.dropna(subset=["lat", "lon"])
    # 2. coordenadas fuera de rango válido: Mongo rechaza geometrías inválidas con el índice 2dsphere
    df = df[df["lat"].between(-90, 90) & df["lon"].between(-180, 180)]
    # 3. fecha inválida: sin marca de tiempo no hay análisis temporal
    df["ts"] = pd.to_datetime(df["fecha"].astype(str) + " " + df["hora"].astype(str), errors="coerce")
    df = df.dropna(subset=["ts"])

    # la altitud -777 es el valor "sin dato" de Geolife: se deja como nula en vez de -777 pies.
    # Además se convierte de pies a metros (1 pie = 0,3048 m).
    alt_m = df["alt_ft"] * 0.3048
    df["alt_m"] = alt_m.where(df["alt_ft"] != -777)

    # el usuario y la trayectoria no vienen en las columnas: salen de la ruta del archivo
    # .../Data/000/Trajectory/20081023025304.plt  ->  usuario 0, trayectoria 20081023025304
    ruta = df["ruta"].astype(str)
    partes = ruta.str.extract(r"Data/(\d+)/Trajectory/(\d+)\.plt")
    df["usuario"] = pd.to_numeric(partes[0], errors="coerce")
    df["trayectoria"] = partes[1]
    df = df.dropna(subset=["usuario", "trayectoria"])
    df["usuario"] = df["usuario"].astype("int32")

    # 4. duplicados exactos (mismo usuario, trayectoria y momento): contarían dos veces el mismo punto
    df = df.drop_duplicates(subset=["usuario", "trayectoria", "ts"])
    return df[["usuario", "trayectoria", "ts", "lat", "lon", "alt_m"]].reset_index(drop=True)


def a_geojson(df):
    """Convierte cada fila en un documento de Mongo con un punto GeoJSON y campos de tiempo local."""
    # ts se guarda en UTC; hora, día y mes se calculan en hora de Pekín (UTC+8) porque
    # "a qué hora del día" solo tiene sentido en la hora local de donde se grabó el GPS
    local = df["ts"] + pd.Timedelta(hours=OFFSET_LOCAL_HORAS)
    docs = []
    for fila, lt in zip(df.itertuples(index=False), local):
        alt = None if pd.isna(fila.alt_m) else float(fila.alt_m)
        docs.append({
            "usuario": int(fila.usuario),
            "trayectoria": fila.trayectoria,
            "ts": fila.ts.to_pydatetime(),
            "altitud_m": alt,
            "hora": int(lt.hour),
            "dia_semana": int(lt.dayofweek),  # 0 = lunes ... 6 = domingo
            "mes": int(lt.month),
            "anio": int(lt.year),
            # GeoJSON exige el orden [longitud, latitud] (al revés de como se suele decir "lat, lon")
            "loc": {"type": "Point", "coordinates": [float(fila.lon), float(fila.lat)]},
        })
    return docs
