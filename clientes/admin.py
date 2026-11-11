from django.contrib import admin

from .models import Cliente


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'telefono', 'restaurante', 'creado_en')
    list_filter = ('restaurante',)
    search_fields = ('nombre', 'telefono')
