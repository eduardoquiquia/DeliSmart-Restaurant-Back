import logging

from django.utils import timezone

from ..models import Conversacion, Mensaje
from . import cliente_whatsapp

logger = logging.getLogger('delismart.whatsapp')


def enviar_mensaje(conversacion: Conversacion, texto: str, autor: str = Mensaje.Autor.ASISTENTE) -> Mensaje:
    """Guarda el mensaje saliente y lo envía por WhatsApp (salvo en chats del simulador)."""
    mensaje = Mensaje.objects.create(
        conversacion=conversacion,
        direccion=Mensaje.Direccion.SALIENTE,
        autor=autor,
        tipo=Mensaje.Tipo.TEXTO,
        texto=texto,
        estado_envio='simulado' if conversacion.simulada else 'pendiente',
    )
    if not conversacion.simulada:
        try:
            resultado = cliente_whatsapp.enviar_texto(
                conversacion.restaurante.whatsapp_phone_number_id, conversacion.telefono, texto
            )
            mensaje.wa_message_id = resultado['id']
            mensaje.estado_envio = 'simulado' if resultado['simulado'] else 'enviado'
        except Exception as error:  # Un fallo de Meta no debe romper el flujo del pedido.
            logger.exception('No se pudo enviar el mensaje %s: %s', mensaje.pk, error)
            mensaje.estado_envio = 'error'
        mensaje.save(update_fields=['wa_message_id', 'estado_envio'])

    Conversacion.objects.filter(pk=conversacion.pk).update(ultimo_mensaje_en=timezone.now())
    return mensaje
