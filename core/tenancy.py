"""Aislamiento multi-tenant: base y esquema compartidos, filtrados siempre por restaurante."""

from django.db.models import ProtectedError
from rest_framework import serializers, viewsets

from .permissions import RolPermitido


def restaurante_de(request):
    return getattr(request.user, 'restaurante', None)


class TenantMixin:
    """Filtra cada consulta por el restaurante del usuario y lo asigna al crear."""

    permission_classes = viewsets.GenericViewSet.permission_classes + [RolPermitido]

    def get_queryset(self):
        return super().get_queryset().filter(restaurante=restaurante_de(self.request))

    def perform_create(self, serializer):
        serializer.save(restaurante=restaurante_de(self.request))

    def perform_destroy(self, instance):
        try:
            instance.delete()
        except ProtectedError:
            raise serializers.ValidationError(
                {'detail': 'No se puede eliminar: tiene registros asociados (pedidos o platos).'}
            )


class TenantViewSet(TenantMixin, viewsets.ModelViewSet):
    pass


class TenantReadOnlyViewSet(TenantMixin, viewsets.ReadOnlyModelViewSet):
    pass


class TenantPrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField):
    """Una FK solo acepta objetos del mismo restaurante: evita mezclar datos entre tenants."""

    def get_queryset(self):
        queryset = super().get_queryset()
        request = self.context.get('request')
        return queryset.filter(restaurante=restaurante_de(request)) if request else queryset.none()
