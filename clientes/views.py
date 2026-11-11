import re

from django.db.models import Count, Max, Q, Sum
from rest_framework import filters, serializers

from core.models import Usuario
from core.tenancy import TenantViewSet

from .models import Cliente


def normalizar_telefono(value):
    digits = re.sub(r'\D', '', value or '')
    # Un celular peruano de 9 dígitos se guarda con el código de país, como lo envía WhatsApp.
    if len(digits) == 9 and digits.startswith('9'):
        digits = f'51{digits}'
    return digits


class ClienteSerializer(serializers.ModelSerializer):
    total_pedidos = serializers.IntegerField(read_only=True)
    total_gastado = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    ultimo_pedido = serializers.DateTimeField(read_only=True)

    class Meta:
        model = Cliente
        fields = (
            'id', 'nombre', 'telefono', 'direccion', 'referencia', 'latitud', 'longitud', 'notas',
            'creado_en', 'total_pedidos', 'total_gastado', 'ultimo_pedido',
        )
        read_only_fields = ('id', 'creado_en')

    def validate_telefono(self, value):
        telefono = normalizar_telefono(value)
        if len(telefono) < 8:
            raise serializers.ValidationError('Ingresa un teléfono válido.')
        request = self.context['request']
        repetido = Cliente.objects.filter(restaurante=request.user.restaurante, telefono=telefono)
        if self.instance:
            repetido = repetido.exclude(pk=self.instance.pk)
        if repetido.exists():
            raise serializers.ValidationError('Ya hay un cliente con ese teléfono.')
        return telefono


class ClienteViewSet(TenantViewSet):
    queryset = Cliente.objects.annotate(
        total_pedidos=Count('pedidos', filter=~Q(pedidos__estado='cancelado')),
        total_gastado=Sum('pedidos__total', filter=Q(pedidos__estado='entregado')),
        ultimo_pedido=Max('pedidos__creado_en'),
    )
    serializer_class = ClienteSerializer
    roles_lectura = (Usuario.Rol.ADMIN, Usuario.Rol.CAJERO)
    roles_escritura = (Usuario.Rol.ADMIN, Usuario.Rol.CAJERO)
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['nombre', 'telefono', 'direccion']
    ordering_fields = ['creado_en', 'nombre', 'total_pedidos', 'total_gastado']
    ordering = ['-creado_en']
