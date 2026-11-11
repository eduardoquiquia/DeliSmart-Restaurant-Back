from decimal import Decimal

from django.db import transaction
from django.db.models import F
from rest_framework import filters, serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from core.models import Usuario
from core.tenancy import TenantViewSet

from .models import Insumo, MovimientoInventario


class InsumoSerializer(serializers.ModelSerializer):
    bajo_stock = serializers.BooleanField(read_only=True)
    unidad_nombre = serializers.CharField(source='get_unidad_display', read_only=True)

    class Meta:
        model = Insumo
        fields = (
            'id', 'nombre', 'unidad', 'unidad_nombre', 'stock', 'stock_minimo', 'costo_unitario',
            'proveedor', 'bajo_stock', 'actualizado_en',
        )
        read_only_fields = ('id', 'actualizado_en')

    def validate_nombre(self, value):
        request = self.context['request']
        repetido = Insumo.objects.filter(restaurante=request.user.restaurante, nombre__iexact=value)
        if self.instance:
            repetido = repetido.exclude(pk=self.instance.pk)
        if repetido.exists():
            raise serializers.ValidationError('Ya existe un insumo con ese nombre.')
        return value


class MovimientoSerializer(serializers.ModelSerializer):
    usuario_nombre = serializers.CharField(source='usuario.__str__', read_only=True, default='')

    class Meta:
        model = MovimientoInventario
        fields = ('id', 'tipo', 'cantidad', 'stock_resultante', 'motivo', 'usuario_nombre', 'creado_en')
        read_only_fields = ('id', 'stock_resultante', 'usuario_nombre', 'creado_en')

    def validate(self, attrs):
        if attrs['tipo'] != MovimientoInventario.Tipo.AJUSTE and attrs['cantidad'] <= 0:
            raise serializers.ValidationError({'cantidad': 'La cantidad debe ser mayor a cero.'})
        if attrs['tipo'] == MovimientoInventario.Tipo.AJUSTE and attrs['cantidad'] < 0:
            raise serializers.ValidationError({'cantidad': 'El stock no puede ser negativo.'})
        return attrs


class InsumoViewSet(TenantViewSet):
    queryset = Insumo.objects.all()
    serializer_class = InsumoSerializer
    roles_lectura = (Usuario.Rol.ADMIN, Usuario.Rol.COCINA)
    roles_escritura = (Usuario.Rol.ADMIN, Usuario.Rol.COCINA)
    filter_backends = [filters.SearchFilter]
    search_fields = ['nombre', 'proveedor']
    pagination_class = None

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get('alerta') == 'true':
            queryset = queryset.filter(stock__lte=F('stock_minimo'))
        return queryset

    @action(detail=False)
    def alertas(self, request):
        insumos = self.filter_queryset(super().get_queryset().filter(stock__lte=F('stock_minimo')))
        return Response(InsumoSerializer(insumos, many=True, context=self.get_serializer_context()).data)

    @action(detail=True, methods=['get', 'post'], serializer_class=MovimientoSerializer)
    def movimientos(self, request, pk=None):
        insumo = self.get_object()
        if request.method == 'GET':
            movimientos = insumo.movimientos.select_related('usuario')[:50]
            return Response(MovimientoSerializer(movimientos, many=True).data)

        serializer = MovimientoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tipo = serializer.validated_data['tipo']
        cantidad = serializer.validated_data['cantidad']
        with transaction.atomic():
            insumo = Insumo.objects.select_for_update().get(pk=insumo.pk)
            if tipo == MovimientoInventario.Tipo.ENTRADA:
                insumo.stock += cantidad
            elif tipo == MovimientoInventario.Tipo.SALIDA:
                insumo.stock = max(Decimal('0'), insumo.stock - cantidad)
            else:
                insumo.stock = cantidad
            insumo.save(update_fields=['stock', 'actualizado_en'])
            serializer.save(
                restaurante=insumo.restaurante, insumo=insumo, usuario=request.user, stock_resultante=insumo.stock
            )
        return Response(
            {'insumo': InsumoSerializer(insumo).data, 'movimiento': serializer.data}, status=201
        )
