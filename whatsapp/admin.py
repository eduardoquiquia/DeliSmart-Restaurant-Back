from django.contrib import admin

from .models import Conversacion, Mensaje


class MensajeInline(admin.TabularInline):
    model = Mensaje
    extra = 0
    fields = ('direccion', 'autor', 'tipo', 'texto', 'creado_en')
    readonly_fields = ('creado_en',)


@admin.register(Conversacion)
class ConversacionAdmin(admin.ModelAdmin):
    list_display = ('telefono', 'cliente', 'restaurante', 'estado', 'simulada', 'ultimo_mensaje_en')
    list_filter = ('restaurante', 'estado', 'simulada')
    inlines = (MensajeInline,)
