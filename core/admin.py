from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Restaurante, Usuario


@admin.register(Restaurante)
class RestauranteAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'subdominio', 'licencia_estado', 'licencia_vencimiento')
    search_fields = ('nombre', 'subdominio')


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ('username', 'email', 'rol', 'restaurante', 'is_active')
    list_filter = ('rol', 'restaurante')
    fieldsets = UserAdmin.fieldsets + (('DeliSmart', {'fields': ('restaurante', 'rol', 'telefono')}),)
