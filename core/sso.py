"""Acceso directo desde "Mi Plan" de delismart-admin-saas.

El backend admin firma con INTERNAL_API_TOKEN (django.core.signing, mismo salt) los datos del
restaurante, de su dueño y de la licencia. Aquí se verifica la firma, se descarta el enlace si
ya se usó o tiene más de SSO_MAX_AGE_SECONDS, y se crea o vincula la pollería y su administrador.
Así, todo cliente que se registra en el landing tiene usuario en el panel desde su primer clic.
"""

from datetime import date

from django.conf import settings
from django.core import signing
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.text import slugify

from .models import Restaurante, TokenSSOUsado, Usuario

SSO_SALT = 'delismart.restaurant-sso'


class TokenSSOInvalido(Exception):
    pass


def _leer(token):
    if not settings.INTERNAL_API_TOKEN:
        raise TokenSSOInvalido('El acceso directo no está configurado en el panel de la pollería.')
    try:
        data = signing.loads(
            token, key=settings.INTERNAL_API_TOKEN, salt=SSO_SALT, max_age=settings.SSO_MAX_AGE_SECONDS,
        )
    except signing.SignatureExpired:
        raise TokenSSOInvalido('El enlace venció. Vuelve a abrir el panel desde Mi Plan.')
    except signing.BadSignature:
        raise TokenSSOInvalido('El enlace no es válido.')
    try:
        return str(data['jti']), dict(data['restaurante']), data.get('usuario') or {}, data.get('licencia') or {}
    except (KeyError, TypeError, ValueError):
        raise TokenSSOInvalido('El enlace no es válido.')


def _sincronizar_restaurante(datos, licencia):
    subdominio = str(datos.get('subdominio') or '').strip().lower()
    if not subdominio:
        raise TokenSSOInvalido('El enlace no es válido.')
    restaurante, _ = Restaurante.objects.get_or_create(
        subdominio=subdominio,
        defaults={
            'nombre': datos.get('nombre') or subdominio,
            'ruc': datos.get('ruc') or '',
            'telefono': datos.get('telefono') or '',
        },
    )
    # La licencia del enlace es la del backend admin en ese momento.
    estado = licencia.get('estado')
    if estado in Restaurante.EstadoLicencia.values:
        vencimiento = licencia.get('fecha_vencimiento')
        restaurante.licencia_estado = estado
        restaurante.licencia_plan = licencia.get('plan') or ''
        restaurante.licencia_vencimiento = date.fromisoformat(vencimiento) if vencimiento else None
        restaurante.licencia_verificada_en = timezone.now()
        restaurante.save()
    return restaurante


def _username_libre(base):
    base = (slugify(base) or 'admin')[:140]
    username, n = base, 1
    while Usuario.objects.filter(username__iexact=username).exists():
        n += 1
        username = f'{base}-{n}'
    return username


def _administrador(restaurante, datos):
    email = str(datos.get('email') or '').strip()
    user = None
    if email:
        user = Usuario.objects.filter(restaurante=restaurante, email__iexact=email).order_by('id').first()
    if user is None:
        base = email.split('@')[0] if email else f'admin-{restaurante.subdominio}'
        user = Usuario(
            username=_username_libre(base),
            email=email,
            first_name=str(datos.get('first_name') or '')[:150],
            last_name=str(datos.get('last_name') or '')[:150],
            restaurante=restaurante,
            rol=Usuario.Rol.ADMIN,
        )
        # Entra con el acceso directo; puede fijar una contraseña desde Usuarios.
        user.set_unusable_password()
        user.save()
    elif user.rol != Usuario.Rol.ADMIN:
        user.rol = Usuario.Rol.ADMIN
        user.save(update_fields=['rol'])
    if not user.is_active:
        raise TokenSSOInvalido('Tu usuario está desactivado en el panel de la pollería.')
    return user


def canjear_token(token):
    jti, datos_restaurante, datos_usuario, licencia = _leer(token)
    try:
        with transaction.atomic():
            TokenSSOUsado.objects.create(jti=jti[:64])
            restaurante = _sincronizar_restaurante(datos_restaurante, licencia)
            return _administrador(restaurante, datos_usuario)
    except IntegrityError:
        raise TokenSSOInvalido('Este enlace ya se usó. Vuelve a abrir el panel desde Mi Plan.')
