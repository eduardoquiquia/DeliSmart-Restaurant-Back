from django.conf import settings
from django.db import models

from core.models import TenantModel


class Insumo(TenantModel):
    class Unidad(models.TextChoices):
        KG = 'kg', 'Kilogramos'
        G = 'g', 'Gramos'
        L = 'l', 'Litros'
        UNIDAD = 'unidad', 'Unidades'
        PAQUETE = 'paquete', 'Paquetes'

    nombre = models.CharField(max_length=120)
    unidad = models.CharField(max_length=10, choices=Unidad, default=Unidad.UNIDAD)
    stock = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    stock_minimo = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    costo_unitario = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    proveedor = models.CharField(max_length=120, blank=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('nombre',)
        constraints = [
            models.UniqueConstraint(fields=('restaurante', 'nombre'), name='insumo_unico_por_restaurante'),
        ]

    def __str__(self):
        return self.nombre

    @property
    def bajo_stock(self):
        return self.stock <= self.stock_minimo


class MovimientoInventario(TenantModel):
    class Tipo(models.TextChoices):
        ENTRADA = 'entrada', 'Entrada'
        SALIDA = 'salida', 'Salida'
        AJUSTE = 'ajuste', 'Ajuste'

    insumo = models.ForeignKey(Insumo, on_delete=models.CASCADE, related_name='movimientos')
    tipo = models.CharField(max_length=10, choices=Tipo)
    cantidad = models.DecimalField(max_digits=10, decimal_places=2)
    stock_resultante = models.DecimalField(max_digits=10, decimal_places=2)
    motivo = models.CharField(max_length=255, blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-creado_en',)
