"""Reglas del ciclo de vida de un pedido, compartidas por el panel y el canal de WhatsApp."""

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import HistorialEstado, ItemPedido, Pedido

AVISOS_CLIENTE = {
    Pedido.Estado.EN_PREPARACION: '✅ Confirmamos tu pago. Tu pedido #{numero} ya está en preparación.',
    Pedido.Estado.EN_CAMINO: '🛵 Tu pedido #{numero} va en camino. ¡Ya casi llega!',
    Pedido.Estado.ENTREGADO: '🍗 Pedido #{numero} entregado. ¡Gracias por tu compra y buen provecho!',
    Pedido.Estado.CANCELADO: 'Tu pedido #{numero} fue cancelado. {motivo}',
}


def tiempo_estimado(restaurante, tiempo_traslado_min):
    return restaurante.tiempo_preparacion_min + (tiempo_traslado_min or 0)


@transaction.atomic
def crear_pedido(*, restaurante, cliente, items, usuario=None, **datos):
    """`items` es una lista de dicts con plato (o nombre y precio_unitario), cantidad y notas."""
    if not items:
        raise ValidationError({'items': 'El pedido necesita al menos un plato.'})

    datos.setdefault('costo_delivery', restaurante.costo_delivery)
    if datos.get('tiempo_estimado_min') is None:
        datos['tiempo_estimado_min'] = tiempo_estimado(restaurante, datos.get('tiempo_traslado_min'))
    pedido = Pedido.objects.create(restaurante=restaurante, cliente=cliente, **datos)

    for item in items:
        plato = item.get('plato')
        ItemPedido.objects.create(
            pedido=pedido,
            plato=plato,
            nombre=item.get('nombre') or plato.nombre,
            precio_unitario=item.get('precio_unitario') or plato.precio,
            cantidad=item.get('cantidad', 1),
            notas=item.get('notas', ''),
        )
    pedido.recalcular_totales()
    pedido.save(update_fields=['subtotal', 'total', 'monto_adelanto'])
    HistorialEstado.objects.create(pedido=pedido, estado=pedido.estado, usuario=usuario, nota=f'Creado ({pedido.get_origen_display()})')
    return pedido


def _avisar_cliente(pedido, motivo=''):
    if pedido.origen != Pedido.Origen.WHATSAPP or pedido.conversacion_id is None:
        return
    plantilla = AVISOS_CLIENTE.get(pedido.estado)
    if not plantilla:
        return
    from whatsapp.servicios.mensajeria import enviar_mensaje

    texto = plantilla.format(numero=pedido.numero, motivo=motivo).strip()
    transaction.on_commit(lambda: enviar_mensaje(pedido.conversacion, texto, autor='sistema'))


@transaction.atomic
def cambiar_estado(pedido, nuevo_estado, usuario=None, nota=''):
    pedido = Pedido.objects.select_for_update().get(pk=pedido.pk)
    if not pedido.puede_pasar_a(nuevo_estado):
        raise ValidationError({
            'estado': f'No se puede pasar de "{pedido.get_estado_display()}" a "{Pedido.Estado(nuevo_estado).label}".'
        })
    if (
        nuevo_estado == Pedido.Estado.EN_PREPARACION
        and pedido.origen == Pedido.Origen.WHATSAPP
        and not pedido.pago_confirmado
    ):
        raise ValidationError({'estado': 'Primero confirma el pago del comprobante.'})

    pedido.estado = nuevo_estado
    campos = ['estado', 'actualizado_en']
    if nuevo_estado == Pedido.Estado.CANCELADO:
        pedido.motivo_cancelacion = nota
        campos.append('motivo_cancelacion')
    pedido.save(update_fields=campos)
    HistorialEstado.objects.create(pedido=pedido, estado=nuevo_estado, usuario=usuario, nota=nota)
    _avisar_cliente(pedido, motivo=nota)
    return pedido


@transaction.atomic
def confirmar_pago(pedido, usuario):
    """El cajero valida el comprobante: el pago queda confirmado y el pedido pasa a cocina."""
    pedido = Pedido.objects.select_for_update().get(pk=pedido.pk)
    if pedido.estado != Pedido.Estado.PENDIENTE_VALIDACION:
        raise ValidationError({'detail': 'Solo se confirma el pago de pedidos pendientes de validación.'})
    pedido.pago_confirmado = True
    pedido.pago_confirmado_por = usuario
    pedido.pago_confirmado_en = timezone.now()
    pedido.save(update_fields=['pago_confirmado', 'pago_confirmado_por', 'pago_confirmado_en', 'actualizado_en'])
    return cambiar_estado(pedido, Pedido.Estado.EN_PREPARACION, usuario, nota='Pago confirmado')
