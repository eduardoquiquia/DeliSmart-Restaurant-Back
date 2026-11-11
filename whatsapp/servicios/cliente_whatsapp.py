"""Cliente de Meta WhatsApp Cloud API: firma del webhook, envío de mensajes y descarga de medios.

TODO(credenciales): requiere WHATSAPP_TOKEN (token permanente de un usuario del sistema),
WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_VERIFY_TOKEN y WHATSAPP_APP_SECRET, además de los permisos
`whatsapp_business_messaging` y `whatsapp_business_management` aprobados por Meta.
"""

import hashlib
import hmac
import logging

import requests
from django.conf import settings

from .integraciones import simulado

logger = logging.getLogger('delismart.whatsapp')

GRAPH_URL = 'https://graph.facebook.com'
TIMEOUT_SECONDS = 10


class ErrorWhatsApp(Exception):
    pass


def firma_valida(cuerpo: bytes, cabecera: str | None, secreto: str | None = None) -> bool:
    """Valida X-Hub-Signature-256: HMAC-SHA256 del cuerpo crudo con el App Secret de Meta."""
    secreto = secreto if secreto is not None else settings.WHATSAPP_APP_SECRET
    if not secreto or not cabecera or not cabecera.startswith('sha256='):
        return False
    esperado = hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, cabecera.removeprefix('sha256='))


def _url(path):
    return f'{GRAPH_URL}/{settings.WHATSAPP_API_VERSION}/{path}'


def _headers():
    return {'Authorization': f'Bearer {settings.WHATSAPP_TOKEN}'}


def enviar_texto(phone_number_id: str, destino: str, texto: str) -> dict:
    """Envía un texto. En modo simulado no sale nada a Meta y se devuelve un id local."""
    if simulado('whatsapp'):
        logger.info('[simulado] WhatsApp a %s: %s', destino, texto[:80])
        return {'simulado': True, 'id': None}

    response = requests.post(
        _url(f'{phone_number_id or settings.WHATSAPP_PHONE_NUMBER_ID}/messages'),
        headers=_headers(),
        json={
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': destino,
            'type': 'text',
            'text': {'preview_url': False, 'body': texto},
        },
        timeout=TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        logger.error('Meta rechazó el mensaje a %s: %s', destino, response.text[:300])
        raise ErrorWhatsApp(response.text[:300])
    data = response.json()
    return {'simulado': False, 'id': (data.get('messages') or [{}])[0].get('id')}


def descargar_media(media_id: str) -> tuple[bytes, str]:
    """Descarga una imagen recibida (p. ej. el comprobante). Devuelve (contenido, mime)."""
    if simulado('whatsapp'):
        raise ErrorWhatsApp('La descarga de medios necesita credenciales reales de WhatsApp.')
    meta = requests.get(_url(media_id), headers=_headers(), timeout=TIMEOUT_SECONDS)
    meta.raise_for_status()
    info = meta.json()
    archivo = requests.get(info['url'], headers=_headers(), timeout=TIMEOUT_SECONDS)
    archivo.raise_for_status()
    return archivo.content, info.get('mime_type', 'image/jpeg')
