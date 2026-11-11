"""Traduce el payload del webhook de Meta a mensajes `Entrante` del pipeline."""

import logging

from django.conf import settings

from core.models import Restaurante

from ..models import Mensaje
from . import cliente_whatsapp
from .pipeline import Entrante, procesar_mensaje

logger = logging.getLogger('delismart.webhook')


def _restaurante_para(phone_number_id):
    restaurante = Restaurante.objects.filter(whatsapp_phone_number_id=phone_number_id).first()
    # Con un solo número de prueba en Meta, WHATSAPP_PHONE_NUMBER_ID apunta a un restaurante demo.
    if restaurante is None and phone_number_id == settings.WHATSAPP_PHONE_NUMBER_ID:
        restaurante = Restaurante.objects.order_by('id').first()
    return restaurante


def _entrante(mensaje, nombres):
    telefono = mensaje.get('from', '')
    base = {
        'telefono': telefono,
        'nombre': nombres.get(telefono, ''),
        'wa_message_id': mensaje.get('id'),
        'payload': mensaje,
    }
    tipo = mensaje.get('type')
    if tipo == 'text':
        return Entrante(tipo=Mensaje.Tipo.TEXTO, texto=mensaje['text'].get('body', ''), **base)
    if tipo == 'location':
        ubicacion = mensaje['location']
        return Entrante(
            tipo=Mensaje.Tipo.UBICACION,
            latitud=ubicacion.get('latitude'),
            longitud=ubicacion.get('longitude'),
            direccion=ubicacion.get('address') or ubicacion.get('name') or '',
            **base,
        )
    if tipo == 'image':
        imagen = None
        try:
            imagen, _ = cliente_whatsapp.descargar_media(mensaje['image']['id'])
        except Exception as error:  # Sin credenciales la imagen no se puede bajar.
            logger.warning('No se pudo descargar la imagen %s: %s', mensaje['image'].get('id'), error)
        return Entrante(
            tipo=Mensaje.Tipo.IMAGEN,
            texto=mensaje['image'].get('caption', ''),
            imagen=imagen,
            imagen_nombre=f"{mensaje['image'].get('id', 'comprobante')}.jpg",
            **base,
        )
    if tipo == 'interactive':
        respuesta = mensaje['interactive'].get('button_reply') or mensaje['interactive'].get('list_reply') or {}
        return Entrante(tipo=Mensaje.Tipo.TEXTO, texto=respuesta.get('title', ''), **base)
    return Entrante(tipo=Mensaje.Tipo.OTRO, texto=f'[{tipo}]', **base)


def procesar_payload(payload):
    """Procesa todos los mensajes del payload. Devuelve cuántos se procesaron."""
    procesados = 0
    for entry in payload.get('entry', []):
        for change in entry.get('changes', []):
            value = change.get('value', {})
            phone_number_id = value.get('metadata', {}).get('phone_number_id', '')
            mensajes = value.get('messages', [])
            if not mensajes:
                continue  # Notificaciones de estado (sent, delivered, read).
            restaurante = _restaurante_para(phone_number_id)
            if restaurante is None:
                logger.warning('Ningún restaurante usa el phone_number_id %s.', phone_number_id)
                continue
            nombres = {c.get('wa_id'): c.get('profile', {}).get('name', '') for c in value.get('contacts', [])}
            for mensaje in mensajes:
                if procesar_mensaje(restaurante, _entrante(mensaje, nombres)).procesado:
                    procesados += 1
    return procesados
