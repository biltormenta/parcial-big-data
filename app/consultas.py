from datetime import datetime

# Límite máximo de registros permitidos por consulta para evitar saturación de memoria
LIMITE_MAX = 5000

# Proyección de campos seleccionados al consultar MongoDB (excluyendo el _id predeterminado)
CAMPOS = {"_id": 0, "usuario": 1, "trayectoria": 1, "ts": 1, "altitud_m": 1, "hora": 1, "loc": 1}


class ParametroInvalido(ValueError):
    """Excepción personalizada para capturar errores de validación en parámetros de entrada."""
    pass


def validar_punto(lat, lon):
    """Valida que las coordenadas de latitud y longitud estén dentro de los rangos geográficos permitidos."""
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        raise ParametroInvalido("lat y lon deben ser numeros")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ParametroInvalido("lat debe estar entre -90 y 90 y lon entre -180 y 180")
    return lat, lon


def validar_radio(radio):
    """Valida que el radio de búsqueda en metros sea un valor numérico válido y positivo."""
    try:
        radio = float(radio)
    except (TypeError, ValueError):
        raise ParametroInvalido("radio debe ser un numero (metros)")
    
    # ------------------------------------------------------------------------------------------
    # CÓDIGO ORIGINAL (ACTIVO): Rango máximo permitido de 100,000 metros (100 km)
    # ------------------------------------------------------------------------------------------
    if not 0 < radio <= 100000:
        raise ParametroInvalido("radio debe estar entre 1 y 100000 metros")

    # >>> PARA LA SUSTENTACIÓN: Si el profesor pide limitar el radio máximo a 50 km (50,000 metros),
    # COMENTAR la condición de arriba y DESCOMENTAR las siguientes 2 líneas: <<<
    # if not 0 < radio <= 50000:
    #     raise ParametroInvalido("radio debe estar entre 1 y 50000 metros")

    return radio


def validar_limite(limite, defecto=100):
    """Valida y aplica topes al número límite de registros solicitados por el usuario."""
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
    """Garantiza la estructura GeoJSON válida para un Polygon o MultiPolygon con anillos cerrados."""
    # El polígono puede llegar "suelto" o envuelto en un Feature (así lo exporta geojson.io); se acepta cualquiera
    geom = entrada
    if isinstance(geom, dict) and geom.get("type") == "Feature":
        geom = geom.get("geometry")
    if not isinstance(geom, dict) or geom.get("type") not in ("Polygon", "MultiPolygon"):
        raise ParametroInvalido("se espera un GeoJSON de tipo Polygon o MultiPolygon")
    coords = geom.get("coordinates")
    if not isinstance(coords, list) or not coords:
        raise ParametroInvalido("el poligono no tiene coordenadas")
    # Un Polygon es una lista de anillos; un MultiPolygon es una lista de polígonos: se aplanan para revisar todos los anillos
    anillos = coords if geom["type"] == "Polygon" else [a for p in coords for a in p]
    for anillo in anillos:
        # Regla de GeoJSON: un anillo cerrado necesita mínimo 4 posiciones y la última igual a la primera
        if not isinstance(anillo, list) or len(anillo) < 4 or anillo[0] != anillo[-1]:
            raise ParametroInvalido("cada anillo necesita minimo 4 posiciones y cerrar en el mismo punto inicial")
        for pos in anillo:
            # En GeoJSON cada posición es [lon, lat]; validar_punto recibe (lat, lon), por eso va al revés
            validar_punto(pos[1], pos[0])
    return geom


def _feature(doc):
    """Transforma un documento con formato MongoDB a un objeto de tipo GeoJSON Feature."""
    d = dict(doc)
    loc = d.pop("loc")
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return {"type": "Feature", "geometry": loc, "properties": d}


def coleccion_fc(docs):
    """Estructura una lista de documentos en una entidad GeoJSON FeatureCollection."""
    feats = [_feature(d) for d in docs]
    return {"type": "FeatureCollection", "count": len(feats), "features": feats}


def cercanos(col, lat, lon, radio_m, limite):
    """Consulta puntos cercanos dentro de un radio usando el operador espacial $near de MongoDB."""
    # $near usa el índice 2dsphere y devuelve los resultados ORDENADOS del más cercano al más lejano.
    # El punto va en orden [lon, lat] y $maxDistance está en metros.
    filtro = {"loc": {"$near": {"$geometry": {"type": "Point", "coordinates": [lon, lat]},
                                "$maxDistance": radio_m}}}
    return list(col.find(filtro, CAMPOS).limit(limite))


def dentro_poligono(col, geom, limite):
    """Consulta puntos que se encuentran contenidos dentro de una geometría usando $geoWithin."""
    # $geoWithin devuelve los puntos que caen dentro del polígono recibido (sin ningún orden en particular)
    filtro = {"loc": {"$geoWithin": {"$geometry": geom}}}
    return list(col.find(filtro, CAMPOS).limit(limite))


def geonear_por_campo(col, lat, lon, radio_m, campo="hora"):
    """Ejecuta un pipeline de agregación usando $geoNear para calcular promedios y métricas según el campo agrupador."""
    
    # ------------------------------------------------------------------------------------------
    # CÓDIGO ORIGINAL (ACTIVO): Pipeline estándar de agregación geoespacial
    # ------------------------------------------------------------------------------------------
    pipeline = [
        # Etapa 1: $geoNear DEBE ser la primera del pipeline. Filtra por radio (metros) y agrega a cada
        # documento su distancia al punto en el campo "dist_m"
        {"$geoNear": {"near": {"type": "Point", "coordinates": [lon, lat]},
                      "distanceField": "dist_m", "maxDistance": radio_m,
                      "spherical": True, "key": "loc"}},
        # Etapa 2: agrupa por el campo elegido (hora, día, mes o año) y calcula cuántos puntos hay,
        # la distancia media y los usuarios distintos (addToSet no repite valores)
        {"$group": {"_id": f"${campo}", "puntos": {"$sum": 1},
                    "dist_media_m": {"$avg": "$dist_m"}, "usuarios": {"$addToSet": "$usuario"}}},
        # Etapa 3: da forma a la salida (el _id del grupo pasa a llamarse como el campo, redondea la distancia, cuenta usuarios)
        {"$project": {"_id": 0, campo: "$_id", "puntos": 1,
                      "dist_media_m": {"$round": ["$dist_media_m", 1]},
                      "usuarios_distintos": {"$size": "$usuarios"}}},
        # Etapa 4: ordena por el campo temporal de menor a mayor (0h, 1h, 2h... / lunes, martes...)
        {"$sort": {campo: 1}},
    ]

    # >>> PARA LA SUSTENTACIÓN: Si el profesor pide ordenar los resultados por cantidad de puntos DESCENDENTE
    # (en lugar de ordenar por el campo temporal), COMENTAR la etapa '$sort' original y DESCOMENTAR la siguiente opción: <<<
    # pipeline = [
    #     {"$geoNear": {"near": {"type": "Point", "coordinates": [lon, lat]},
    #                   "distanceField": "dist_m", "maxDistance": radio_m,
    #                   "spherical": True, "key": "loc"}},
    #     {"$group": {"_id": f"${campo}", "puntos": {"$sum": 1},
    #                 "dist_media_m": {"$avg": "$dist_m"}, "usuarios": {"$addToSet": "$usuario"}}},
    #     {"$project": {"_id": 0, campo: "$_id", "puntos": 1,
    #                   "dist_media_m": {"$round": ["$dist_media_m", 1]},
    #                   "usuarios_distintos": {"$size": "$usuarios"}}},
    #     {"$sort": {"puntos": -1}},
    # ]

    return list(col.aggregate(pipeline))