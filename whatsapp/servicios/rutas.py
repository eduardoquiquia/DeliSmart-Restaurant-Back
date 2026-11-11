"""Distancia y tiempo de traslado con Google Maps Routes API, y verificación de cobertura.

TODO(credenciales): requiere GOOGLE_MAPS_API_KEY con la Routes API habilitada en Google Cloud.
Sin clave se estima con la distancia en línea recta (haversine) por un factor urbano.
"""

import logging
import math
import re
from dataclasses import dataclass
from decimal import Decimal

import requests

from .integraciones import simulado

logger = logging.getLogger('delismart.rutas')

ROUTES_URL = 'https://routes.googleapis.com/directions/v2:computeRoutes'
TIMEOUT_SECONDS = 8
# Las calles hacen que el recorrido real sea más largo que la línea recta.
FACTOR_URBANO = 1.3
VELOCIDAD_MOTO_KMH = 25


@dataclass
class Ruta:
    distancia_km: Decimal
    tiempo_min: int
    simulada: bool


def haversine_km(lat1, lng1, lat2, lng2):
    radio = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radio * math.asin(math.sqrt(a))


def _ruta_estimada(origen, destino):
    km = haversine_km(*origen, *destino) * FACTOR_URBANO
    minutos = max(1, round(km / VELOCIDAD_MOTO_KMH * 60))
    return Ruta(Decimal(str(round(km, 2))), minutos, True)


def calcular_ruta(origen: tuple[float, float], destino: tuple[float, float]) -> Ruta:
    from django.conf import settings

    if simulado('google_maps'):
        return _ruta_estimada(origen, destino)

    def punto(lat, lng):
        return {'location': {'latLng': {'latitude': lat, 'longitude': lng}}}

    try:
        response = requests.post(
            ROUTES_URL,
            headers={
                'X-Goog-Api-Key': settings.GOOGLE_MAPS_API_KEY,
                'X-Goog-FieldMask': 'routes.distanceMeters,routes.duration',
            },
            json={
                'origin': punto(*origen),
                'destination': punto(*destino),
                'travelMode': 'TWO_WHEELER',
                'routingPreference': 'TRAFFIC_AWARE',
                'languageCode': 'es-PE',
            },
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        ruta = response.json()['routes'][0]
        segundos = int(re.sub(r'\D', '', ruta['duration']) or 0)
        return Ruta(Decimal(ruta['distanceMeters']) / 1000, max(1, round(segundos / 60)), False)
    except (requests.RequestException, KeyError, IndexError, ValueError) as error:
        logger.warning('Routes API falló, se usa la estimación: %s', error)
        return _ruta_estimada(origen, destino)


def ruta_desde_restaurante(restaurante, lat, lng) -> Ruta | None:
    if not restaurante.tiene_ubicacion:
        return None
    return calcular_ruta((float(restaurante.latitud), float(restaurante.longitud)), (float(lat), float(lng)))


def dentro_de_cobertura(restaurante, ruta: Ruta | None) -> bool:
    # Sin ubicación del local no se puede medir: el cajero decide al validar.
    return ruta is None or ruta.distancia_km <= restaurante.radio_cobertura_km
