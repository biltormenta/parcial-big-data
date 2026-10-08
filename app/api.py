import os

from flask import Flask, jsonify, render_template, request
from pymongo import MongoClient
from pymongo.errors import OperationFailure

from app import config, consultas
from app.consultas import ParametroInvalido

app = Flask(__name__)
_cliente = None

# colecciones que deja el job de spark
RESULTADOS_SPARK = {
    "grilla": ("spark_grilla", [("n", -1)]),
    "zonas": ("spark_zonas_calientes", [("ranking", 1)]),
    "hora": ("spark_por_hora", [("hora", 1)]),
    "dia": ("spark_por_dia", [("dia_semana", 1)]),
    "mes": ("spark_por_mes", [("anio", 1), ("mes", 1)]),
}


def db():
    global _cliente
    if _cliente is None:
        _cliente = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=3000)
    return _cliente[config.MONGO_DB]


@app.errorhandler(ParametroInvalido)
def parametro_invalido(e):
    return jsonify(error=str(e)), 400


@app.errorhandler(OperationFailure)
def error_mongo(e):
    # mongo rechaza geometrias malformadas (anillos que se cruzan, etc)
    return jsonify(error=f"mongo rechazo la consulta: {e.details.get('errmsg', str(e))}"), 400


@app.get("/")
def mapa():
    return render_template("mapa.html")


@app.get("/health")
def health():
    db().command("ping")
    return jsonify(status="ok", puntos=db()[config.COLECCION_PUNTOS].estimated_document_count())


@app.get("/api/cercanos")
def cercanos():
    lat, lon = consultas.validar_punto(request.args.get("lat"), request.args.get("lon"))
    radio = consultas.validar_radio(request.args.get("radio"))
    limite = consultas.validar_limite(request.args.get("limit"))
    docs = consultas.cercanos(db()[config.COLECCION_PUNTOS], lat, lon, radio, limite)
    return jsonify(consultas.coleccion_fc(docs))


@app.post("/api/poligono")
def poligono():
    cuerpo = request.get_json(silent=True)
    if cuerpo is None:
        raise ParametroInvalido("el cuerpo debe ser un JSON con el poligono GeoJSON")
    geom = consultas.validar_poligono(cuerpo)
    limite = consultas.validar_limite(request.args.get("limit"))
    docs = consultas.dentro_poligono(db()[config.COLECCION_PUNTOS], geom, limite)
    return jsonify(consultas.coleccion_fc(docs))


@app.get("/api/geonear")
def geonear():
    lat, lon = consultas.validar_punto(request.args.get("lat"), request.args.get("lon"))
    radio = consultas.validar_radio(request.args.get("radio"))
    campo = request.args.get("por", "hora")
    if campo not in ("hora", "dia_semana", "mes", "anio"):
        raise ParametroInvalido("por debe ser hora, dia_semana, mes o anio")
    filas = consultas.geonear_por_campo(db()[config.COLECCION_PUNTOS], lat, lon, radio, campo)
    return jsonify(por=campo, total=sum(f["puntos"] for f in filas), resultados=filas)


@app.get("/api/spark/<nombre>")
def spark(nombre):
    if nombre not in RESULTADOS_SPARK:
        raise ParametroInvalido(f"resultado desconocido, opciones: {', '.join(RESULTADOS_SPARK)}")
    coleccion, orden = RESULTADOS_SPARK[nombre]
    limite = consultas.validar_limite(request.args.get("limit"), defecto=50)
    docs = list(db()[coleccion].find({}, {"_id": 0}).sort(orden).limit(limite))
    return jsonify(resultado=nombre, count=len(docs), datos=docs)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
