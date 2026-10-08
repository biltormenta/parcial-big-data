import datetime
import os

import pytest
import requests
from pymongo import GEOSPHERE, MongoClient

# Configuración de variables de entorno para apuntar a la API y MongoDB
API = os.getenv("API_URL", "http://localhost:5000")
MONGO = os.getenv("MONGO_URI", "mongodb://mongo:27017")
DB = os.getenv("MONGO_DB", "geolife")

# Coordenadas de prueba situadas en el Atlántico para evitar interferencias con datos reales de Pekín
LAT0, LON0 = 0.0, -30.0
CERCA = [(0.0, -30.0), (0.0003, -30.0003), (-0.0003, -30.0002), (0.0002, -29.9997), (-0.0002, -29.9996)]
LEJOS = [(0.009, -30.0), (0.0, -29.991), (-0.009, -30.0)]


@pytest.fixture(scope="module", autouse=True)
def datos_de_prueba():
    """Fixture que inserta puntos sintéticos marcados con '_prueba': True antes de los tests y los elimina al finalizar."""
    col = MongoClient(MONGO)[DB]["puntos"]
    col.create_index([("loc", GEOSPHERE)])
    ts = datetime.datetime(2009, 5, 4, 10, 0, 0)
    docs = [{"_prueba": True, "usuario": i, "trayectoria": "t", "ts": ts, "altitud_m": None, "hora": 18,
             "dia_semana": 0, "mes": 5, "anio": 2009, "loc": {"type": "Point", "coordinates": [lon, lat]}}
            for i, (lat, lon) in enumerate(CERCA + LEJOS)]
    col.insert_many(docs)
    yield
    # Limpieza automática en la base de datos tras la ejecución de las pruebas
    col.delete_many({"_prueba": True})


def test_health():
    """Valida que el servicio esté arriba y responda con status 200 y 'ok'."""
    r = requests.get(f"{API}/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_cercanos_por_radio():
    """Verifica la consulta de cercanía según el radio en metros."""
    r = requests.get(f"{API}/api/cercanos", params={"lat": LAT0, "lon": LON0, "radio": 200})
    assert r.status_code == 200
    assert r.json()["count"] == len(CERCA)
    r = requests.get(f"{API}/api/cercanos", params={"lat": LAT0, "lon": LON0, "radio": 2000})
    assert r.json()["count"] == len(CERCA) + len(LEJOS)


def test_cercanos_respeta_limit():
    """Comprueba que el parámetro 'limit' restrinja correctamente el número de registros devueltos."""
    r = requests.get(f"{API}/api/cercanos", params={"lat": LAT0, "lon": LON0, "radio": 2000, "limit": 2})
    assert r.json()["count"] == 2


def test_poligono():
    """Valida la consulta geoespacial dentro de una caja o polígono GeoJSON y dentro de una Feature."""
    caja = {"type": "Polygon", "coordinates": [[[-30.001, -0.001], [-29.999, -0.001], [-29.999, 0.001],
                                                [-30.001, 0.001], [-30.001, -0.001]]]}
    r = requests.post(f"{API}/api/poligono", json=caja)
    assert r.status_code == 200 and r.json()["count"] == len(CERCA)
    
    # También se comprueba que acepte la geometría envuelta en un objeto tipo Feature
    r = requests.post(f"{API}/api/poligono", json={"type": "Feature", "properties": {}, "geometry": caja})
    assert r.json()["count"] == len(CERCA)


def test_geonear_agregacion():
    """Prueba la agregación de $geoNear agrupada por hora."""
    r = requests.get(f"{API}/api/geonear", params={"lat": LAT0, "lon": LON0, "radio": 200, "por": "hora"})
    j = r.json()
    assert r.status_code == 200 and j["total"] == len(CERCA)
    assert j["resultados"][0]["hora"] == 18


def test_resultados_spark_responde():
    """Verifica que las colecciones precalculadas por Spark devuelvan datos correctamente."""
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
    """Garantiza que la API responda HTTP 400 ante parámetros erróneos o fuera de rango."""
    assert requests.get(f"{API}{ruta}", params=params).status_code == 400


def test_poligono_invalido_da_400():
    """Comprueba que el envío de geometrías GeoJSON no válidas retorne un error HTTP 400."""
    assert requests.post(f"{API}/api/poligono", json={"type": "Point", "coordinates": [0, 0]}).status_code == 400


# ======================================================================================
# BLOQUE DE SUSTENTACIÓN (PRUEBAS ADICIONALES)
# ======================================================================================

# >>> PARA LA SUSTENTACIÓN: Si el profesor pide probar el nuevo endpoint /api/sustentacion o validar radios negativos
# Descomenta las siguientes funciones:

# def test_endpoint_sustentacion():
#     r = requests.get(f"{API}/api/sustentacion")
#     assert r.status_code == 200
#     assert r.json()["estado"] == "exitoso"

# def test_radio_negativo_da_400():
#     r = requests.get(f"{API}/api/cercanos", params={"lat": LAT0, "lon": LON0, "radio": -50})
#     assert r.status_code == 400