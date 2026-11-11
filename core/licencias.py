"""Verificación de licencias contra delismart-admin-saas-back.

Antes de abrir el panel o procesar un mensaje de WhatsApp se comprueba que la licencia del
restaurante esté ACTIVA y no haya vencido. El backend admin es la fuente de verdad; la
respuesta se guarda en el restaurante y se reutiliza durante LICENSE_CACHE_SECONDS.

TODO(credenciales): delismart-admin-saas-back todavía no expone el endpoint interno.
Debe responder `GET {ADMIN_SAAS_API_URL}/api/internal/licencias/<subdominio>/` con el header
`Authorization: Bearer <INTERNAL_API_TOKEN>` y un JSON como:
    {"estado": "activa", "plan": "pro", "fecha_vencimiento": "2026-12-31"}
Mientras no exista, deja ADMIN_SAAS_API_URL vacío y la licencia local manda.
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta

import requests
from django.conf import settings
from django.utils import timezone

from .models import Restaurante

logger = logging.getLogger('delismart.licencias')

TIMEOUT_SECONDS = 4


@dataclass
class ResultadoLicencia:
    vigente: bool
    estado: str
    vencimiento: date | None
    fuente: str  # admin_api, cache o local
    motivo: str = ''


def _resultado_local(restaurante, fuente):
    vigente = restaurante.licencia_vigente
    motivo = ''
    if not vigente:
        if restaurante.licencia_estado == Restaurante.EstadoLicencia.ACTIVA:
            motivo = 'La licencia del restaurante venció.'
        else:
            motivo = f'La licencia del restaurante está {restaurante.get_licencia_estado_display().lower()}.'
    return ResultadoLicencia(vigente, restaurante.licencia_estado, restaurante.licencia_vencimiento, fuente, motivo)


def _consultar_admin(restaurante):
    url = f'{settings.ADMIN_SAAS_API_URL}/api/internal/licencias/{restaurante.subdominio}/'
    response = requests.get(
        url,
        headers={'Authorization': f'Bearer {settings.INTERNAL_API_TOKEN}'},
        timeout=TIMEOUT_SECONDS,
    )
    if response.status_code == 404:
        return {'estado': Restaurante.EstadoLicencia.SIN_LICENCIA, 'plan': '', 'fecha_vencimiento': None}
    response.raise_for_status()
    return response.json()


def verificar_licencia(restaurante, forzar=False):
    if restaurante is None:
        return ResultadoLicencia(False, Restaurante.EstadoLicencia.SIN_LICENCIA, None, 'local', 'Usuario sin restaurante.')

    if not settings.ADMIN_SAAS_API_URL:
        return _resultado_local(restaurante, 'local')

    verificada = restaurante.licencia_verificada_en
    if not forzar and verificada and timezone.now() - verificada < timedelta(seconds=settings.LICENSE_CACHE_SECONDS):
        return _resultado_local(restaurante, 'cache')

    try:
        data = _consultar_admin(restaurante)
    except (requests.RequestException, ValueError) as error:
        logger.warning('No se pudo consultar la licencia de %s: %s', restaurante.subdominio, error)
        if settings.LICENSE_FALLBACK == 'local':
            return _resultado_local(restaurante, 'local')
        return ResultadoLicencia(
            False, restaurante.licencia_estado, restaurante.licencia_vencimiento, 'admin_api',
            'No se pudo verificar la licencia con DeliSmart.',
        )

    estado = data.get('estado') or Restaurante.EstadoLicencia.SIN_LICENCIA
    if estado not in Restaurante.EstadoLicencia.values:
        estado = Restaurante.EstadoLicencia.SIN_LICENCIA
    vencimiento = data.get('fecha_vencimiento')
    restaurante.licencia_estado = estado
    restaurante.licencia_plan = data.get('plan') or ''
    restaurante.licencia_vencimiento = date.fromisoformat(vencimiento) if vencimiento else None
    restaurante.licencia_verificada_en = timezone.now()
    restaurante.save(update_fields=[
        'licencia_estado', 'licencia_plan', 'licencia_vencimiento', 'licencia_verificada_en', 'actualizado_en',
    ])
    return _resultado_local(restaurante, 'admin_api')
