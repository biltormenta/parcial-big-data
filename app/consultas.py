from datetime import datetime

LIMITE_MAX = 5000
CAMPOS = {"_id": 0, "usuario": 1, "trayectoria": 1, "ts": 1, "altitud_m": 1, "hora": 1, "loc": 1}


class ParametroInvalido(ValueError):
    pass


def validar_punto(lat, lon):
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        raise ParametroInvalido("lat y lon deben ser numeros")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ParametroInvalido("lat debe estar entre -90 y 90 y lon entre -180 y 180")
    return lat, lon


def validar_radio(radio):
    try:
        radio = float(radio)
    except (TypeError, ValueError):
        raise ParametroInvalido("radio debe ser un numero (metros)")
    if not 0 < radio <= 100000:
        raise ParametroInvalido("radio debe estar entre 1 y 100000 metros")
    return radio


def validar_limite(limite, defecto=100):
    if limite in (None, ""):
        return defecto
    try:
        limite = int(limite)
    except (TypeError, ValueError):
        raise ParametroInvalido("limit debe ser un entero")
    if limite < 1:
        raise ParametroInvalido("limit debe ser mayor a 0")
    return min(limite, LIMITE_MAX)


def validar_poligono(entrada):
    # acepta el poligono suelto o dentro de un Feature
    geom = entrada
    if isinstance(geom, dict) and geom.get("type") == "Feature":
        geom = geom.get("geometry")
    if not isinstance(geom, dict) or geom.get("type") not in ("Polygon", "MultiPolygon"):
        raise ParametroInvalido("se espera un GeoJSON de tipo Polygon o MultiPolygon")
    coords = geom.get("coordinates")
    if not isinstance(coords, list) or not coords:
        raise ParametroInvalido("el poligono no tiene coordenadas")
    anillos = coords if geom["type"] == "Polygon" else [a for p in coords for a in p]
    for anillo in anillos:
        if not isinstance(anillo, list) or len(anillo) < 4 or anillo[0] != anillo[-1]:
            raise ParametroInvalido("cada anillo necesita minimo 4 posiciones y cerrar en el mismo punto inicial")
        for pos in anillo:
            validar_punto(pos[1], pos[0])
    return geom


def _feature(doc):
    d = dict(doc)
    loc = d.pop("loc")
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return {"type": "Feature", "geometry": loc, "properties": d}


def coleccion_fc(docs):
    feats = [_feature(d) for d in docs]
    return {"type": "FeatureCollection", "count": len(feats), "features": feats}


def cercanos(col, lat, lon, radio_m, limite):
    # $near ya devuelve ordenado de mas cerca a mas lejos
    filtro = {"loc": {"$near": {"$geometry": {"type": "Point", "coordinates": [lon, lat]},
                                "$maxDistance": radio_m}}}
    return list(col.find(filtro, CAMPOS).limit(limite))


def dentro_poligono(col, geom, limite):
    filtro = {"loc": {"$geoWithin": {"$geometry": geom}}}
    return list(col.find(filtro, CAMPOS).limit(limite))


def geonear_por_campo(col, lat, lon, radio_m, campo="hora"):
    # $geoNear tiene que ser la primera etapa del pipeline
    pipeline = [
        {"$geoNear": {"near": {"type": "Point", "coordinates": [lon, lat]},
                      "distanceField": "dist_m", "maxDistance": radio_m,
                      "spherical": True, "key": "loc"}},
        {"$group": {"_id": f"${campo}", "puntos": {"$sum": 1},
                    "dist_media_m": {"$avg": "$dist_m"}, "usuarios": {"$addToSet": "$usuario"}}},
        {"$project": {"_id": 0, campo: "$_id", "puntos": 1,
                      "dist_media_m": {"$round": ["$dist_media_m", 1]},
                      "usuarios_distintos": {"$size": "$usuarios"}}},
        {"$sort": {campo: 1}},
    ]
    return list(col.aggregate(pipeline))
