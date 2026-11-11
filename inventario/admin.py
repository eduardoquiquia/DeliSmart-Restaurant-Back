from django.contrib import admin

from .models import Insumo, MovimientoInventario


@admin.register(Insumo)
class InsumoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'stock', 'stock_minimo', 'unidad', 'restaurante')
    list_filter = ('restaurante',)


admin.site.register(MovimientoInventario)
