from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class Restaurante(models.Model):
    """Copia local del tenant del backend admin, con la configuración operativa de la pollería.

    El `subdominio` es la llave compartida con `tenants.Tenant` de delismart-admin-saas-back.
    """

    class EstadoLicencia(models.TextChoices):
        ACTIVA = 'activa', 'Activa'
        VENCIDA = 'vencida', 'Vencida'
        CANCELADA = 'cancelada', 'Cancelada'
        SIN_LICENCIA = 'sin_licencia', 'Sin licencia'

    nombre = models.CharField(max_length=120)
    subdominio = models.CharField(max_length=63, unique=True)
    ruc = models.CharField(max_length=11, blank=True)
    telefono = models.CharField(max_length=30, blank=True)
    logo = models.ImageField(upload_to='logos/', blank=True)

    # Ubicación y cobertura de delivery.
    direccion = models.CharField(max_length=255, blank=True)
    latitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    radio_cobertura_km = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('5.00'))
    tiempo_preparacion_min = models.PositiveIntegerField(default=25)
    costo_delivery = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('0.00'))

    # Datos de pago que el asistente comparte con el cliente.
    yape_numero = models.CharField(max_length=20, blank=True)
    yape_titular = models.CharField(max_length=120, blank=True)
    plin_numero = models.CharField(max_length=20, blank=True)
    plin_titular = models.CharField(max_length=120, blank=True)
    transferencia_banco = models.CharField(max_length=60, blank=True)
    transferencia_cuenta = models.CharField(max_length=40, blank=True)
    transferencia_cci = models.CharField(max_length=40, blank=True)
    transferencia_titular = models.CharField(max_length=120, blank=True)

    # WhatsApp: el phone_number_id de Meta identifica al restaurante en el webhook.
    whatsapp_numero = models.CharField(max_length=20, blank=True)
    whatsapp_phone_number_id = models.CharField(max_length=40, blank=True, db_index=True)
    mensaje_bienvenida = models.CharField(max_length=500, blank=True)
    bot_activo = models.BooleanField(default=True)

    # Última licencia conocida, sincronizada desde el backend admin (o editada a mano sin él).
    licencia_estado = models.CharField(
        max_length=15, choices=EstadoLicencia, default=EstadoLicencia.SIN_LICENCIA
    )
    licencia_plan = models.CharField(max_length=20, blank=True)
    licencia_vencimiento = models.DateField(null=True, blank=True)
    licencia_verificada_en = models.DateTimeField(null=True, blank=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.nombre} ({self.subdominio})'

    @property
    def licencia_vigente(self):
        return (
            self.licencia_estado == self.EstadoLicencia.ACTIVA
            and self.licencia_vencimiento is not None
            and self.licencia_vencimiento >= timezone.localdate()
        )

    @property
    def tiene_ubicacion(self):
        return self.latitud is not None and self.longitud is not None


class Usuario(AbstractUser):
    """Personal de la pollería. Cada usuario pertenece a un solo restaurante."""

    class Rol(models.TextChoices):
        ADMIN = 'admin', 'Administrador'
        CAJERO = 'cajero', 'Cajero'
        COCINA = 'cocina', 'Cocina'

    restaurante = models.ForeignKey(
        Restaurante, null=True, blank=True, on_delete=models.CASCADE, related_name='usuarios'
    )
    rol = models.CharField(max_length=10, choices=Rol, default=Rol.CAJERO)
    telefono = models.CharField(max_length=30, blank=True)

    def __str__(self):
        return self.get_full_name() or self.username


class TenantModel(models.Model):
    """Base de toda tabla operativa: siempre cuelga de un restaurante."""

    restaurante = models.ForeignKey(Restaurante, on_delete=models.CASCADE, related_name='+')

    class Meta:
        abstract = True


class TokenSSOUsado(models.Model):
    """Accesos directos ya canjeados: cada enlace desde Mi Plan sirve una sola vez."""

    jti = models.CharField(max_length=64, unique=True)
    usado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'token SSO usado'
        verbose_name_plural = 'tokens SSO usados'
