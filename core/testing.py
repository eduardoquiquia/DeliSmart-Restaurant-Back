"""Fábricas compartidas por las pruebas de todas las apps."""

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APIClient

from carta.models import Categoria, Plato
from clientes.models import Cliente
from core.models import Restaurante, Usuario


def crear_restaurante(subdominio='elsabrosito', dias_licencia=30, **extra):
    datos = {
        'nombre': subdominio.title(),
        'licencia_estado': Restaurante.EstadoLicencia.ACTIVA,
        'licencia_vencimiento': timezone.localdate() + timedelta(days=dias_licencia),
        'latitud': Decimal('-12.119400'),
        'longitud': Decimal('-77.033500'),
        'costo_delivery': Decimal('5.00'),
        'yape_numero': '987111222',
    }
    datos.update(extra)
    return Restaurante.objects.create(subdominio=subdominio, **datos)


def crear_usuario(restaurante, rol=Usuario.Rol.ADMIN, username=None):
    username = username or f'{rol}-{restaurante.subdominio}'
    user = Usuario(username=username, rol=rol, restaurante=restaurante)
    user.set_password('clave-segura-123')
    user.save()
    return user


def cliente_api(user):
    api = APIClient()
    api.force_authenticate(user)
    return api


def crear_carta(restaurante):
    pollos = Categoria.objects.create(restaurante=restaurante, nombre='Pollos')
    bebidas = Categoria.objects.create(restaurante=restaurante, nombre='Bebidas', orden=1)
    entero = Plato.objects.create(
        restaurante=restaurante, categoria=pollos, nombre='Pollo a la brasa entero', precio=Decimal('60.00'),
        alias='pollo entero',
    )
    cuarto = Plato.objects.create(
        restaurante=restaurante, categoria=pollos, nombre='1/4 de pollo a la brasa', precio=Decimal('18.00'),
        alias='1/4 de pollo,cuarto de pollo',
    )
    gaseosa = Plato.objects.create(
        restaurante=restaurante, categoria=bebidas, nombre='Inca Kola 1.5L', precio=Decimal('10.00'),
        alias='inca kola,gaseosa',
    )
    return {'pollos': pollos, 'bebidas': bebidas, 'entero': entero, 'cuarto': cuarto, 'gaseosa': gaseosa}


def crear_cliente(restaurante, telefono='51987654321', nombre='María'):
    return Cliente.objects.create(restaurante=restaurante, telefono=telefono, nombre=nombre)
