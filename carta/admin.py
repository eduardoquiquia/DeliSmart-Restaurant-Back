from django.contrib import admin

from .models import Categoria, Plato


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'restaurante', 'orden', 'activa')
    list_filter = ('restaurante',)


@admin.register(Plato)
class PlatoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'categoria', 'precio', 'disponible', 'restaurante')
    list_filter = ('restaurante', 'disponible')
    search_fields = ('nombre',)
