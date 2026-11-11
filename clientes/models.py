from django.db import models

from core.models import TenantModel


class Cliente(TenantModel):
    nombre = models.CharField(max_length=120, blank=True)
    # Formato internacional sin "+", igual que el `wa_id` de WhatsApp (51987654321).
    telefono = models.CharField(max_length=20)
    direccion = models.CharField(max_length=255, blank=True)
    referencia = models.CharField(max_length=255, blank=True)
    latitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    notas = models.TextField(blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-creado_en',)
        constraints = [
            models.UniqueConstraint(fields=('restaurante', 'telefono'), name='cliente_telefono_por_restaurante'),
        ]

    def __str__(self):
        return self.nombre or self.telefono
