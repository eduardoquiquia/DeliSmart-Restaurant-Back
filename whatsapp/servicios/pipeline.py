"""Procesa cada mensaje entrante, venga del webhook de Meta o del simulador del panel.

1. Verifica la licencia del restaurante.
2. Registra cliente, conversación y mensaje (idempotente por wa_message_id).
3. Ubicación → ruta y cobertura. Imagen → comprobante. Texto → asistente.
4. Si el borrador está completo, crea el pedido en `pendiente_validacion`.
5. Envía las respuestas y las guarda en la conversación.
"""

import logging
from dataclasses import dataclass, field
from decimal import Decimal

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from carta.models import Plato
from clientes.models import Cliente
from core.licencias import verificar_licencia
from pedidos.models import Pedido
from pedidos.servicios import crear_pedido

from ..models import Conversacion, Mensaje
from . import asistente
from .herramientas import Herramientas, soles
from .mensajeria import enviar_mensaje

logger = logging.getLogger('delismart.pipeline')


@dataclass
class Entrante:
    telefono: str
    tipo: str = Mensaje.Tipo.TEXTO
    texto: str = ''
    nombre: str = ''
    latitud: float | None = None
    longitud: float | None = None
    direccion: str = ''
    imagen: object = None  # Archivo de Django (simulador) o bytes descargados de Meta.
    imagen_nombre: str = 'comprobante.jpg'
    wa_message_id: str | None = None
    payload: dict | None = None


@dataclass
class Resultado:
    procesado: bool
    motivo: str = ''
    conversacion: Conversacion | None = None
    pedido: Pedido | None = None
    respuestas: list = field(default_factory=list)


def _registrar(restaurante, entrante, simulada):
    cliente, _ = Cliente.objects.get_or_create(
        restaurante=restaurante, telefono=entrante.telefono, defaults={'nombre': entrante.nombre}
    )
    if entrante.nombre and not cliente.nombre:
        cliente.nombre = entrante.nombre
        cliente.save(update_fields=['nombre', 'actualizado_en'])
    conversacion, _ = Conversacion.objects.get_or_create(
        restaurante=restaurante, telefono=entrante.telefono, defaults={'cliente': cliente, 'simulada': simulada}
    )
    mensaje = Mensaje(
        conversacion=conversacion,
        direccion=Mensaje.Direccion.ENTRANTE,
        autor=Mensaje.Autor.CLIENTE,
        tipo=entrante.tipo,
        texto=entrante.texto or entrante.direccion,
        latitud=entrante.latitud,
        longitud=entrante.longitud,
        wa_message_id=entrante.wa_message_id,
        payload=entrante.payload,
    )
    if entrante.imagen is not None:
        contenido = entrante.imagen if isinstance(entrante.imagen, bytes) else entrante.imagen.read()
        mensaje.imagen.save(entrante.imagen_nombre, ContentFile(contenido), save=False)
    mensaje.save()
    Conversacion.objects.filter(pk=conversacion.pk).update(
        ultimo_mensaje_en=timezone.now(), no_leidos=conversacion.no_leidos + 1
    )
    conversacion.refresh_from_db()
    return conversacion, mensaje


def _cerrar_pedido(herramientas):
    """Convierte el borrador completo en un pedido real para que el cajero valide el pago."""
    conversacion = herramientas.conversacion
    borrador = herramientas.borrador
    comprobante = Mensaje.objects.filter(pk=borrador.get('comprobante_mensaje_id'), conversacion=conversacion).first()
    platos = {p.id: p for p in Plato.objects.filter(restaurante=conversacion.restaurante, id__in=[i['plato_id'] for i in borrador['items']])}
    items = [
        {'plato': platos.get(i['plato_id']), 'nombre': i['nombre'], 'precio_unitario': Decimal(i['precio']),
         'cantidad': i['cantidad'], 'notas': i.get('notas', '')}
        for i in borrador['items']
    ]
    pedido = crear_pedido(
        restaurante=conversacion.restaurante,
        cliente=conversacion.cliente,
        items=items,
        conversacion=conversacion,
        origen=Pedido.Origen.WHATSAPP,
        metodo_pago=borrador['metodo_pago'],
        porcentaje_adelanto=borrador['porcentaje_adelanto'],
        direccion_entrega=borrador.get('direccion', ''),
        referencia=borrador.get('referencia', ''),
        latitud=Decimal(str(borrador['latitud'])).quantize(Decimal('0.000001')),
        longitud=Decimal(str(borrador['longitud'])).quantize(Decimal('0.000001')),
        distancia_km=Decimal(str(borrador['distancia_km'])) if borrador.get('distancia_km') is not None else None,
        tiempo_traslado_min=borrador.get('tiempo_traslado_min'),
    )
    if comprobante and comprobante.imagen:
        pedido.comprobante.save(comprobante.imagen.name.rsplit('/', 1)[-1], comprobante.imagen.file, save=True)

    cliente = conversacion.cliente
    if borrador.get('direccion') and not cliente.direccion:
        cliente.direccion = borrador['direccion']
        cliente.latitud, cliente.longitud = pedido.latitud, pedido.longitud
        cliente.save(update_fields=['direccion', 'latitud', 'longitud', 'actualizado_en'])
    herramientas.vaciar()
    return pedido


def _respuesta_pedido_creado(pedido):
    return (
        f'🙌 ¡Recibimos tu comprobante! Tu pedido *#{pedido.numero}* por {soles(pedido.total)} '
        f'quedó registrado y estamos validando tu pago de {soles(pedido.monto_adelanto)}.\n'
        f'🕒 Tiempo estimado de entrega: {pedido.tiempo_estimado_min} min. Te avisaremos por aquí.'
    )


def procesar_mensaje(restaurante, entrante: Entrante, simulada=False) -> Resultado:
    licencia = verificar_licencia(restaurante)
    if not licencia.vigente:
        logger.warning('Mensaje ignorado: %s no tiene licencia vigente.', restaurante.subdominio)
        return Resultado(False, licencia.motivo or 'Licencia inactiva.')

    if entrante.wa_message_id and Mensaje.objects.filter(wa_message_id=entrante.wa_message_id).exists():
        return Resultado(False, 'Mensaje duplicado.')

    with transaction.atomic():
        conversacion, mensaje = _registrar(restaurante, entrante, simulada)

    if not restaurante.bot_activo or conversacion.estado != Conversacion.Estado.BOT:
        return Resultado(True, 'Atención humana: el asistente no responde.', conversacion)

    herramientas = Herramientas(conversacion)
    respuestas, pedido = [], None

    if entrante.tipo == Mensaje.Tipo.UBICACION and entrante.latitud is not None:
        ruta = herramientas.registrar_ubicacion(entrante.latitud, entrante.longitud, entrante.direccion)
        if ruta['dentro_de_cobertura'] and ruta['distancia_km'] is not None:
            respuestas.append(
                f'📍 ¡Ubicación recibida! Estás a {ruta["distancia_km"]:.1f} km, '
                f'unos {ruta["tiempo_traslado_min"]} min en moto.'
            )
        elif ruta['dentro_de_cobertura']:
            respuestas.append('📍 ¡Ubicación recibida!')
    elif entrante.tipo == Mensaje.Tipo.IMAGEN:
        herramientas.borrador['comprobante_mensaje_id'] = mensaje.pk
        herramientas.guardar()
        if herramientas.datos_faltantes():
            respuestas.append('📸 Guardamos tu comprobante. Antes de registrar el pedido necesitamos un par de datos más.')
    elif entrante.texto:
        respuestas.extend(asistente.responder(conversacion, entrante.texto))
        herramientas = Herramientas(Conversacion.objects.get(pk=conversacion.pk))

    if not herramientas.datos_faltantes() and not herramientas.borrador.get('fuera_de_cobertura'):
        with transaction.atomic():
            pedido = _cerrar_pedido(herramientas)
        respuestas = [_respuesta_pedido_creado(pedido)]
    elif entrante.tipo != Mensaje.Tipo.TEXTO:
        siguiente = herramientas.pedir_datos_faltantes()
        if siguiente:
            respuestas.append(siguiente)

    for texto in respuestas:
        if texto:
            enviar_mensaje(conversacion, texto)
    conversacion.refresh_from_db()
    return Resultado(True, '', conversacion, pedido, respuestas)
