from django.db import models

from core.models import TenantModel


class Categoria(TenantModel):
    nombre = models.CharField(max_length=80)
    descripcion = models.CharField(max_length=255, blank=True)
    orden = models.PositiveIntegerField(default=0)
    activa = models.BooleanField(default=True)

    class Meta:
        ordering = ('orden', 'nombre')
        constraints = [
            models.UniqueConstraint(fields=('restaurante', 'nombre'), name='categoria_unica_por_restaurante'),
        ]

    def __str__(self):
        return self.nombre


class Plato(TenantModel):
    categoria = models.ForeignKey(Categoria, on_delete=models.PROTECT, related_name='platos')
    nombre = models.CharField(max_length=120)
    descripcion = models.CharField(max_length=500, blank=True)
    precio = models.DecimalField(max_digits=8, decimal_places=2)
    imagen = models.ImageField(upload_to='platos/', blank=True)
    disponible = models.BooleanField(default=True)
    # Palabras extra con las que el cliente pide el plato por WhatsApp ("1/4", "cuarto").
    alias = models.CharField(max_length=255, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('categoria__orden', 'nombre')

    def __str__(self):
        return self.nombre
