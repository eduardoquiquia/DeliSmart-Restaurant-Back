from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import models
from django.db.models import Max

from core.models import TenantModel

CENTIMOS = Decimal('0.01')


class Pedido(TenantModel):
    class Origen(models.TextChoices):
        WHATSAPP = 'whatsapp', 'WhatsApp'
        MANUAL = 'manual', 'Manual'

    class Estado(models.TextChoices):
        PENDIENTE_VALIDACION = 'pendiente_validacion', 'Pendiente de validación'
        EN_PREPARACION = 'en_preparacion', 'En preparación'
        EN_CAMINO = 'en_camino', 'En camino'
        ENTREGADO = 'entregado', 'Entregado'
        CANCELADO = 'cancelado', 'Cancelado'

    class MetodoPago(models.TextChoices):
        YAPE = 'yape', 'Yape'
        PLIN = 'plin', 'Plin'
        TRANSFERENCIA = 'transferencia', 'Transferencia'
        EFECTIVO = 'efectivo', 'Efectivo'

    # Flujo permitido; cancelar es posible hasta que el pedido sale del local.
    TRANSICIONES = {
        Estado.PENDIENTE_VALIDACION: (Estado.EN_PREPARACION, Estado.CANCELADO),
        Estado.EN_PREPARACION: (Estado.EN_CAMINO, Estado.CANCELADO),
        Estado.EN_CAMINO: (Estado.ENTREGADO,),
        Estado.ENTREGADO: (),
        Estado.CANCELADO: (),
    }

    numero = models.PositiveIntegerField(editable=False)
    cliente = models.ForeignKey('clientes.Cliente', on_delete=models.PROTECT, related_name='pedidos')
    conversacion = models.ForeignKey(
        'whatsapp.Conversacion', null=True, blank=True, on_delete=models.SET_NULL, related_name='pedidos'
    )
    origen = models.CharField(max_length=10, choices=Origen, default=Origen.MANUAL)
    estado = models.CharField(max_length=25, choices=Estado, default=Estado.PENDIENTE_VALIDACION, db_index=True)

    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    costo_delivery = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # Pago adelantado con comprobante (captura de Yape/Plin/transferencia).
    metodo_pago = models.CharField(max_length=15, choices=MetodoPago, default=MetodoPago.YAPE)
    porcentaje_adelanto = models.PositiveSmallIntegerField(default=100)
    monto_adelanto = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    comprobante = models.ImageField(upload_to='comprobantes/%Y/%m/', blank=True)
    pago_confirmado = models.BooleanField(default=False)
    pago_confirmado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    pago_confirmado_en = models.DateTimeField(null=True, blank=True)

    # Entrega.
    direccion_entrega = models.CharField(max_length=255, blank=True)
    referencia = models.CharField(max_length=255, blank=True)
    latitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    distancia_km = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    tiempo_traslado_min = models.PositiveIntegerField(null=True, blank=True)
    tiempo_estimado_min = models.PositiveIntegerField(null=True, blank=True)

    notas = models.TextField(blank=True)
    motivo_cancelacion = models.CharField(max_length=255, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True, db_index=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-creado_en',)
        constraints = [
            models.UniqueConstraint(fields=('restaurante', 'numero'), name='pedido_numero_por_restaurante'),
            models.CheckConstraint(
                condition=models.Q(porcentaje_adelanto__in=(0, 50, 100)), name='pedido_adelanto_valido'
            ),
        ]

    def __str__(self):
        return f'Pedido #{self.numero}'

    @property
    def saldo_pendiente(self):
        return max(Decimal('0'), self.total - self.monto_adelanto)

    def puede_pasar_a(self, estado):
        return estado in self.TRANSICIONES[self.estado]

    def recalcular_totales(self):
        self.subtotal = sum((item.subtotal for item in self.items.all()), Decimal('0'))
        self.total = self.subtotal + self.costo_delivery
        self.monto_adelanto = (self.total * self.porcentaje_adelanto / 100).quantize(CENTIMOS, ROUND_HALF_UP)

    def save(self, *args, **kwargs):
        if not self.numero:
            ultimo = Pedido.objects.filter(restaurante=self.restaurante_id).aggregate(n=Max('numero'))['n']
            self.numero = (ultimo or 0) + 1
        super().save(*args, **kwargs)


class ItemPedido(models.Model):
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name='items')
    plato = models.ForeignKey('carta.Plato', null=True, blank=True, on_delete=models.SET_NULL)
    # Nombre y precio se copian: la carta puede cambiar después del pedido.
    nombre = models.CharField(max_length=120)
    precio_unitario = models.DecimalField(max_digits=8, decimal_places=2)
    cantidad = models.PositiveIntegerField(default=1)
    notas = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ('id',)

    @property
    def subtotal(self):
        return self.precio_unitario * self.cantidad


class HistorialEstado(models.Model):
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name='historial')
    estado = models.CharField(max_length=25, choices=Pedido.Estado)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    nota = models.CharField(max_length=255, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('creado_en', 'id')
