import pandas as pd

from app.limpieza import a_geojson, estadisticas, limpiar

RUTA = "/data/kaggle/Geolife Trajectories 1.3/Data/004/Trajectory/20081023025304.plt"


def crudo(filas):
    df = pd.DataFrame(filas, columns=["lat", "lon", "alt_ft", "fecha", "hora"])
    df["ruta"] = RUTA
    return df


# Pruebas de las reglas de limpieza con datos armados a mano (sin Dask ni Mongo).
# De 5 filas solo 1 es buena; estadisticas() debe contar cada descarte en su categoría
def test_descarta_nulos_fuera_de_rango_y_fecha_invalida():
    df = crudo([
        ["39.98", "116.31", "492", "2008-10-23", "02:53:04"],   # bueno
        [None, "116.31", "492", "2008-10-23", "02:53:05"],      # lat nula
        ["400.0", "116.31", "492", "2008-10-23", "02:53:06"],   # lat fuera de rango
        ["39.98", "200.0", "492", "2008-10-23", "02:53:07"],    # lon fuera de rango
        ["39.98", "116.31", "492", "xxxx", "02:53:08"],         # fecha mala
    ])
    assert len(limpiar(df)) == 1
    s = estadisticas(df).iloc[0]
    assert (s.leidos, s.nulos, s.fuera_rango, s.sin_fecha) == (5, 1, 2, 1)


# Dos filas idénticas quedan en una; el usuario (4) y la trayectoria salen del nombre del archivo
def test_duplicados_y_extraccion_de_usuario():
    fila = ["39.98", "116.31", "492", "2008-10-23", "02:53:04"]
    out = limpiar(crudo([fila, fila]))
    assert len(out) == 1
    assert out.loc[0, "usuario"] == 4 and out.loc[0, "trayectoria"] == "20081023025304"


# Altitud -777 (sin dato) pasa a nula; 100 pies = 30,48 metros
def test_altitud_sin_dato_queda_nula_y_se_convierte_a_metros():
    out = limpiar(crudo([["39.98", "116.31", "-777", "2008-10-23", "02:53:04"],
                         ["39.98", "116.32", "100", "2008-10-23", "02:53:05"]]))
    assert pd.isna(out.loc[0, "alt_m"])
    assert abs(out.loc[1, "alt_m"] - 30.48) < 1e-6


# El documento de Mongo guarda el punto como [lon, lat] y la hora ya convertida a hora de Pekín (UTC+8)
def test_geojson_es_punto_lon_lat_y_hora_local():
    out = limpiar(crudo([["39.98", "116.31", "492", "2008-10-23", "02:53:04"]]))
    doc = a_geojson(out)[0]
    assert doc["loc"] == {"type": "Point", "coordinates": [116.31, 39.98]}
    assert doc["hora"] == 10  # 02:53 gmt = 10:53 en pekin
    assert doc["dia_semana"] == 3 and doc["mes"] == 10
