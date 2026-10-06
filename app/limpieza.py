import pandas as pd

from app.config import OFFSET_LOCAL_HORAS

COLUMNAS_PLT = ["lat", "lon", "alt_ft", "fecha", "hora"]

META_LIMPIO = pd.DataFrame({
    "usuario": pd.Series(dtype="int32"),
    "trayectoria": pd.Series(dtype="object"),
    "ts": pd.Series(dtype="datetime64[ns]"),
    "lat": pd.Series(dtype="float64"),
    "lon": pd.Series(dtype="float64"),
    "alt_m": pd.Series(dtype="float64"),
})


def estadisticas(df):
    # cuenta cuantos registros se van a descartar y por que (una fila por particion)
    lat = pd.to_numeric(df["lat"], errors="coerce")
    lon = pd.to_numeric(df["lon"], errors="coerce")
    nulos = lat.isna() | lon.isna()
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
    df = df.copy()
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df["alt_ft"] = pd.to_numeric(df["alt_ft"], errors="coerce")

    # 1. coordenadas nulas
    df = df.dropna(subset=["lat", "lon"])
    # 2. coordenadas fuera de rango valido
    df = df[df["lat"].between(-90, 90) & df["lon"].between(-180, 180)]
    # 3. fecha invalida
    df["ts"] = pd.to_datetime(df["fecha"].astype(str) + " " + df["hora"].astype(str), errors="coerce")
    df = df.dropna(subset=["ts"])

    # la altitud -777 es el valor "sin dato" de geolife, la dejo como nula
    alt_m = df["alt_ft"] * 0.3048
    df["alt_m"] = alt_m.where(df["alt_ft"] != -777)

    # el usuario y la trayectoria salen de la ruta .../Data/000/Trajectory/2008...plt
    ruta = df["ruta"].astype(str)
    partes = ruta.str.extract(r"Data/(\d+)/Trajectory/(\d+)\.plt")
    df["usuario"] = pd.to_numeric(partes[0], errors="coerce")
    df["trayectoria"] = partes[1]
    df = df.dropna(subset=["usuario", "trayectoria"])
    df["usuario"] = df["usuario"].astype("int32")

    # 4. duplicados exactos (mismo usuario, trayectoria y momento)
    df = df.drop_duplicates(subset=["usuario", "trayectoria", "ts"])
    return df[["usuario", "trayectoria", "ts", "lat", "lon", "alt_m"]].reset_index(drop=True)


def a_geojson(df):
    # cada fila se vuelve un documento con un punto GeoJSON [lon, lat]
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
            "dia_semana": int(lt.dayofweek),
            "mes": int(lt.month),
            "anio": int(lt.year),
            "loc": {"type": "Point", "coordinates": [float(fila.lon), float(fila.lat)]},
        })
    return docs
