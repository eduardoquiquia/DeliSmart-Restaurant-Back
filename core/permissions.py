from rest_framework.exceptions import APIException
from rest_framework.permissions import SAFE_METHODS, BasePermission

from .licencias import verificar_licencia
from .models import Usuario


class LicenciaInactiva(APIException):
    status_code = 402
    default_detail = 'La licencia del restaurante no está activa.'
    default_code = 'licencia_inactiva'


class LicenciaVigente(BasePermission):
    """Middleware de licencia del panel: sin licencia ACTIVA y vigente no hay acceso a los datos."""

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return True  # IsAuthenticated responde antes con 401.
        resultado = verificar_licencia(getattr(user, 'restaurante', None))
        if not resultado.vigente:
            raise LicenciaInactiva(resultado.motivo or None)
        return True


class RolPermitido(BasePermission):
    """Lee `roles_lectura` y `roles_escritura` de la vista. Sin ellos, solo el admin escribe."""

    message = 'Tu rol no tiene acceso a esta sección.'

    def has_permission(self, request, view):
        rol = getattr(request.user, 'rol', None)
        if request.method in SAFE_METHODS:
            roles = getattr(view, 'roles_lectura', tuple(Usuario.Rol.values))
        else:
            roles = getattr(view, 'roles_escritura', (Usuario.Rol.ADMIN,))
        return rol in roles


class SoloAdmin(BasePermission):
    message = 'Solo el administrador del restaurante puede hacer esto.'

    def has_permission(self, request, view):
        return getattr(request.user, 'rol', None) == Usuario.Rol.ADMIN
