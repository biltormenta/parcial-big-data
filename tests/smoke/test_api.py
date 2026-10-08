import datetime
import os

import pytest
import requests
from pymongo import GEOSPHERE, MongoClient

API = os.getenv("API_URL", "http://localhost:5000")
MONGO = os.getenv("MONGO_URI", "mongodb://mongo:27017")
DB = os.getenv("MONGO_DB", "geolife")

# punto de prueba en pleno atlantico, para no mezclarse con los datos reales de pekin
LAT0, LON0 = 0.0, -30.0
CERCA = [(0.0, -30.0), (0.0003, -30.0003), (-0.0003, -30.0002), (0.0002, -29.9997), (-0.0002, -29.9996)]
LEJOS = [(0.009, -30.0), (0.0, -29.991), (-0.009, -30.0)]


@pytest.fixture(scope="module", autouse=True)
def datos_de_prueba():
    col = MongoClient(MONGO)[DB]["puntos"]
    col.create_index([("loc", GEOSPHERE)])
    ts = datetime.datetime(2009, 5, 4, 10, 0, 0)
    docs = [{"_prueba": True, "usuario": i, "trayectoria": "t", "ts": ts, "altitud_m": None, "hora": 18,
             "dia_semana": 0, "mes": 5, "anio": 2009, "loc": {"type": "Point", "coordinates": [lon, lat]}}
            for i, (lat, lon) in enumerate(CERCA + LEJOS)]
    col.insert_many(docs)
    yield
    col.delete_many({"_prueba": True})


def test_health():
    r = requests.get(f"{API}/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_cercanos_por_radio():
    r = requests.get(f"{API}/api/cercanos", params={"lat": LAT0, "lon": LON0, "radio": 200})
    assert r.status_code == 200
    assert r.json()["count"] == len(CERCA)
    r = requests.get(f"{API}/api/cercanos", params={"lat": LAT0, "lon": LON0, "radio": 2000})
    assert r.json()["count"] == len(CERCA) + len(LEJOS)


def test_cercanos_respeta_limit():
    r = requests.get(f"{API}/api/cercanos", params={"lat": LAT0, "lon": LON0, "radio": 2000, "limit": 2})
    assert r.json()["count"] == 2


def test_poligono():
    caja = {"type": "Polygon", "coordinates": [[[-30.001, -0.001], [-29.999, -0.001], [-29.999, 0.001],
                                                [-30.001, 0.001], [-30.001, -0.001]]]}
    r = requests.post(f"{API}/api/poligono", json=caja)
    assert r.status_code == 200 and r.json()["count"] == len(CERCA)
    # tambien acepta el poligono dentro de un Feature
    r = requests.post(f"{API}/api/poligono", json={"type": "Feature", "properties": {}, "geometry": caja})
    assert r.json()["count"] == len(CERCA)


def test_geonear_agregacion():
    r = requests.get(f"{API}/api/geonear", params={"lat": LAT0, "lon": LON0, "radio": 200, "por": "hora"})
    j = r.json()
    assert r.status_code == 200 and j["total"] == len(CERCA)
    assert j["resultados"][0]["hora"] == 18


def test_resultados_spark_responde():
    for nombre in ("grilla", "zonas", "hora", "dia", "mes"):
        r = requests.get(f"{API}/api/spark/{nombre}")
        assert r.status_code == 200 and "datos" in r.json()


@pytest.mark.parametrize("ruta,params", [
    ("/api/cercanos", {"lat": "abc", "lon": 1, "radio": 10}),
    ("/api/cercanos", {"lat": 95, "lon": 1, "radio": 10}),
    ("/api/cercanos", {"lat": 1, "lon": 1}),
    ("/api/geonear", {"lat": 1, "lon": 1, "radio": 10, "por": "otro"}),
    ("/api/spark/inexistente", {}),
])
def test_parametros_invalidos_dan_400(ruta, params):
    assert requests.get(f"{API}{ruta}", params=params).status_code == 400


def test_poligono_invalido_da_400():
    assert requests.post(f"{API}/api/poligono", json={"type": "Point", "coordinates": [0, 0]}).status_code == 400
