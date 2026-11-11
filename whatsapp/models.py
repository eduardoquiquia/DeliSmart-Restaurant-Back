from django.db import models

from core.models import TenantModel


def borrador_vacio():
    return {}


class Conversacion(TenantModel):
    """Chat de WhatsApp de un cliente con la pollería. Guarda el pedido que el asistente va armando."""

    class Estado(models.TextChoices):
        BOT = 'bot', 'Atendida por el asistente'
        HUMANO = 'humano', 'Atendida por el personal'
        CERRADA = 'cerrada', 'Cerrada'

    cliente = models.ForeignKey('clientes.Cliente', on_delete=models.CASCADE, related_name='conversaciones')
    telefono = models.CharField(max_length=20)
    estado = models.CharField(max_length=10, choices=Estado, default=Estado.BOT)
    # Pedido en construcción: items, ubicación, método y porcentaje de pago.
    borrador = models.JSONField(default=borrador_vacio, blank=True)
    simulada = models.BooleanField(default=False)
    no_leidos = models.PositiveIntegerField(default=0)
    ultimo_mensaje_en = models.DateTimeField(null=True, blank=True, db_index=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-ultimo_mensaje_en', '-id')
        constraints = [
            models.UniqueConstraint(fields=('restaurante', 'telefono'), name='conversacion_por_telefono'),
        ]

    def __str__(self):
        return f'Chat {self.telefono}'


class Mensaje(models.Model):
    class Direccion(models.TextChoices):
        ENTRANTE = 'entrante', 'Del cliente'
        SALIENTE = 'saliente', 'Del restaurante'

    class Tipo(models.TextChoices):
        TEXTO = 'texto', 'Texto'
        IMAGEN = 'imagen', 'Imagen'
        UBICACION = 'ubicacion', 'Ubicación'
        OTRO = 'otro', 'Otro'

    class Autor(models.TextChoices):
        CLIENTE = 'cliente', 'Cliente'
        ASISTENTE = 'asistente', 'Asistente IA'
        PERSONAL = 'personal', 'Personal'
        SISTEMA = 'sistema', 'Sistema'

    conversacion = models.ForeignKey(Conversacion, on_delete=models.CASCADE, related_name='mensajes')
    direccion = models.CharField(max_length=10, choices=Direccion)
    autor = models.CharField(max_length=10, choices=Autor, default=Autor.CLIENTE)
    tipo = models.CharField(max_length=10, choices=Tipo, default=Tipo.TEXTO)
    texto = models.TextField(blank=True)
    imagen = models.ImageField(upload_to='whatsapp/%Y/%m/', blank=True)
    latitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    # Id de Meta: evita procesar dos veces el mismo mensaje cuando el webhook reintenta.
    wa_message_id = models.CharField(max_length=128, null=True, blank=True, unique=True)
    estado_envio = models.CharField(max_length=15, blank=True)
    payload = models.JSONField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('creado_en', 'id')

    def __str__(self):
        return f'{self.direccion}: {self.texto[:40]}'
