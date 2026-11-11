from django.contrib import admin

from .models import HistorialEstado, ItemPedido, Pedido


class ItemInline(admin.TabularInline):
    model = ItemPedido
    extra = 0


class HistorialInline(admin.TabularInline):
    model = HistorialEstado
    extra = 0


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ('numero', 'restaurante', 'cliente', 'origen', 'estado', 'total', 'creado_en')
    list_filter = ('restaurante', 'estado', 'origen')
    inlines = (ItemInline, HistorialInline)
