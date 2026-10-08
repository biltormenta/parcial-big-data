import pytest

from app.consultas import (ParametroInvalido, validar_limite, validar_poligono, validar_punto,
                           validar_radio)

CAJA = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}


def test_validar_punto():
    assert validar_punto("39.9", "116.4") == (39.9, 116.4)
    for malo in [("a", 1), (91, 0), (0, 181), (None, None)]:
        with pytest.raises(ParametroInvalido):
            validar_punto(*malo)


def test_validar_radio():
    assert validar_radio("500") == 500.0
    for malo in ["0", "-5", "x", None, "200000"]:
        with pytest.raises(ParametroInvalido):
            validar_radio(malo)


def test_validar_limite_usa_defecto_y_tope():
    assert validar_limite(None) == 100
    assert validar_limite("10") == 10
    assert validar_limite("999999") == 5000
    with pytest.raises(ParametroInvalido):
        validar_limite("0")


def test_validar_poligono():
    assert validar_poligono(CAJA) == CAJA
    assert validar_poligono({"type": "Feature", "geometry": CAJA}) == CAJA
    abierto = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1]]]}
    for malo in [abierto, {"type": "Point", "coordinates": [0, 0]}, "hola", {"type": "Polygon"}]:
        with pytest.raises(ParametroInvalido):
            validar_poligono(malo)
