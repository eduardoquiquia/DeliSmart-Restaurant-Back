from datetime import datetime

from django.db.models import Q
from django.utils import timezone
from rest_framework import filters, mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from carta.models import Plato
from clientes.models import Cliente
from clientes.views import normalizar_telefono
from core.models import Usuario
from core.tenancy import TenantMixin, TenantPrimaryKeyRelatedField

from . import servicios
from .models import HistorialEstado, ItemPedido, Pedido

TODOS = tuple(Usuario.Rol.values)
CAJA = (Usuario.Rol.ADMIN, Usuario.Rol.CAJERO)
# La cocina solo mueve los pedidos que ya están en su tablero.
TRANSICIONES_COCINA = {Pedido.Estado.EN_CAMINO}


class ItemPedidoSerializer(serializers.ModelSerializer):
    subtotal = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = ItemPedido
        fields = ('id', 'plato', 'nombre', 'precio_unitario', 'cantidad', 'notas', 'subtotal')


class HistorialSerializer(serializers.ModelSerializer):
    usuario_nombre = serializers.SerializerMethodField()

    class Meta:
        model = HistorialEstado
        fields = ('estado', 'nota', 'usuario_nombre', 'creado_en')

    def get_usuario_nombre(self, historial):
        return str(historial.usuario) if historial.usuario else 'Sistema'


class ClienteResumenSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cliente
        fields = ('id', 'nombre', 'telefono', 'direccion')


class PedidoListaSerializer(serializers.ModelSerializer):
    cliente = ClienteResumenSerializer(read_only=True)
    items = ItemPedidoSerializer(many=True, read_only=True)
    estado_nombre = serializers.CharField(source='get_estado_display', read_only=True)
    saldo_pendiente = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = Pedido
        fields = (
            'id', 'numero', 'cliente', 'origen', 'estado', 'estado_nombre', 'items',
            'subtotal', 'costo_delivery', 'total', 'metodo_pago', 'porcentaje_adelanto', 'monto_adelanto',
            'saldo_pendiente', 'pago_confirmado', 'comprobante', 'direccion_entrega', 'distancia_km',
            'tiempo_traslado_min', 'tiempo_estimado_min', 'notas', 'conversacion', 'creado_en', 'actualizado_en',
        )


class PedidoDetalleSerializer(PedidoListaSerializer):
    historial = HistorialSerializer(many=True, read_only=True)
    pago_confirmado_por = serializers.StringRelatedField()

    class Meta(PedidoListaSerializer.Meta):
        fields = PedidoListaSerializer.Meta.fields + (
            'referencia', 'latitud', 'longitud', 'pago_confirmado_por', 'pago_confirmado_en',
            'motivo_cancelacion', 'historial',
        )


class ItemEntradaSerializer(serializers.Serializer):
    plato = TenantPrimaryKeyRelatedField(queryset=Plato.objects.all())
    cantidad = serializers.IntegerField(min_value=1, max_value=99)
    notas = serializers.CharField(required=False, allow_blank=True, default='')


class PedidoManualSerializer(serializers.Serializer):
    """Pedido registrado por el cajero (teléfono, mostrador)."""

    cliente = TenantPrimaryKeyRelatedField(queryset=Cliente.objects.all(), required=False)
    cliente_telefono = serializers.CharField(required=False, allow_blank=True)
    cliente_nombre = serializers.CharField(required=False, allow_blank=True, default='')
    items = ItemEntradaSerializer(many=True)
    metodo_pago = serializers.ChoiceField(choices=Pedido.MetodoPago.choices, default=Pedido.MetodoPago.EFECTIVO)
    porcentaje_adelanto = serializers.ChoiceField(choices=(0, 50, 100), default=0)
    direccion_entrega = serializers.CharField(required=False, allow_blank=True, default='')
    referencia = serializers.CharField(required=False, allow_blank=True, default='')
    notas = serializers.CharField(required=False, allow_blank=True, default='')
    costo_delivery = serializers.DecimalField(max_digits=8, decimal_places=2, required=False, min_value=0)

    def validate(self, attrs):
        if not attrs.get('cliente') and not normalizar_telefono(attrs.get('cliente_telefono', '')):
            raise serializers.ValidationError({'cliente_telefono': 'Indica el cliente o su teléfono.'})
        if not attrs['items']:
            raise serializers.ValidationError({'items': 'Agrega al menos un plato.'})
        no_disponibles = [i['plato'].nombre for i in attrs['items'] if not i['plato'].disponible]
        if no_disponibles:
            raise serializers.ValidationError({'items': f'No disponible: {", ".join(no_disponibles)}.'})
        return attrs


class CambioEstadoSerializer(serializers.Serializer):
    estado = serializers.ChoiceField(choices=Pedido.Estado.choices)
    nota = serializers.CharField(required=False, allow_blank=True, default='')


def _fecha(valor):
    try:
        return datetime.strptime(valor, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


class PedidoViewSet(TenantMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    queryset = Pedido.objects.select_related('cliente').prefetch_related('items')
    roles_lectura = TODOS
    roles_escritura = TODOS  # Cada acción limita los roles por su cuenta.
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['=numero', 'cliente__nombre', 'cliente__telefono', 'direccion_entrega']
    ordering_fields = ['creado_en', 'numero', 'total']
    ordering = ['-creado_en']

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return PedidoDetalleSerializer
        if self.action == 'create':
            return PedidoManualSerializer
        return PedidoListaSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == 'retrieve':
            queryset = queryset.prefetch_related('historial__usuario').select_related('pago_confirmado_por')
        params = self.request.query_params
        estados = [e for e in params.get('estado', '').split(',') if e in Pedido.Estado.values]
        if estados:
            queryset = queryset.filter(estado__in=estados)
        if params.get('origen') in Pedido.Origen.values:
            queryset = queryset.filter(origen=params['origen'])
        if desde := _fecha(params.get('desde')):
            queryset = queryset.filter(creado_en__date__gte=desde)
        if hasta := _fecha(params.get('hasta')):
            queryset = queryset.filter(creado_en__date__lte=hasta)
        if params.get('hoy') == 'true':
            queryset = queryset.filter(creado_en__date=timezone.localdate())
        return queryset

    def _exigir(self, roles):
        if self.request.user.rol not in roles:
            raise PermissionDenied('Tu rol no puede hacer esto.')

    def create(self, request, *args, **kwargs):
        self._exigir(CAJA)
        serializer = PedidoManualSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        datos = serializer.validated_data
        restaurante = request.user.restaurante
        cliente = datos.get('cliente')
        if cliente is None:
            cliente, _ = Cliente.objects.get_or_create(
                restaurante=restaurante,
                telefono=normalizar_telefono(datos['cliente_telefono']),
                defaults={'nombre': datos['cliente_nombre'], 'direccion': datos['direccion_entrega']},
            )
        extra = {}
        if 'costo_delivery' in datos:
            extra['costo_delivery'] = datos['costo_delivery']
        pedido = servicios.crear_pedido(
            restaurante=restaurante,
            cliente=cliente,
            usuario=request.user,
            items=[{'plato': i['plato'], 'cantidad': i['cantidad'], 'notas': i['notas']} for i in datos['items']],
            origen=Pedido.Origen.MANUAL,
            metodo_pago=datos['metodo_pago'],
            porcentaje_adelanto=int(datos['porcentaje_adelanto']),
            direccion_entrega=datos['direccion_entrega'] or cliente.direccion,
            referencia=datos['referencia'],
            notas=datos['notas'],
            **extra,
        )
        return Response(PedidoDetalleSerializer(pedido, context=self.get_serializer_context()).data, status=201)

    @action(detail=True, methods=['post'], url_path='confirmar-pago')
    def confirmar_pago(self, request, pk=None):
        self._exigir(CAJA)
        pedido = servicios.confirmar_pago(self.get_object(), request.user)
        return Response(PedidoDetalleSerializer(pedido, context=self.get_serializer_context()).data)

    @action(detail=True, methods=['post'])
    def estado(self, request, pk=None):
        serializer = CambioEstadoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        nuevo = serializer.validated_data['estado']
        if request.user.rol == Usuario.Rol.COCINA and nuevo not in TRANSICIONES_COCINA:
            raise PermissionDenied('La cocina solo puede despachar pedidos.')
        pedido = servicios.cambiar_estado(self.get_object(), nuevo, request.user, serializer.validated_data['nota'])
        return Response(PedidoDetalleSerializer(pedido, context=self.get_serializer_context()).data)

    @action(detail=True, methods=['post'], url_path='comprobante')
    def subir_comprobante(self, request, pk=None):
        self._exigir(CAJA)
        pedido = self.get_object()
        archivo = request.FILES.get('comprobante')
        if not archivo:
            return Response({'comprobante': 'Adjunta una imagen.'}, status=status.HTTP_400_BAD_REQUEST)
        pedido.comprobante = archivo
        pedido.save(update_fields=['comprobante', 'actualizado_en'])
        return Response(PedidoDetalleSerializer(pedido, context=self.get_serializer_context()).data)

    @action(detail=False)
    def tablero(self, request):
        """Pedidos activos agrupados por estado, para el tablero de cocina y caja."""
        activos = (
            Pedido.Estado.PENDIENTE_VALIDACION, Pedido.Estado.EN_PREPARACION, Pedido.Estado.EN_CAMINO,
        )
        hoy = timezone.localdate()
        queryset = self.filter_queryset(super().get_queryset()).filter(
            Q(estado__in=activos) | Q(estado=Pedido.Estado.ENTREGADO, actualizado_en__date=hoy)
        ).order_by('creado_en')
        data = PedidoListaSerializer(queryset, many=True, context=self.get_serializer_context()).data
        columnas = {estado: [] for estado in (*activos, Pedido.Estado.ENTREGADO)}
        for pedido in data:
            columnas[pedido['estado']].append(pedido)
        return Response(columnas)

    @action(detail=False)
    def nuevos(self, request):
        """Polling del cajero: pedidos de WhatsApp por validar y el último id visto."""
        queryset = super().get_queryset().filter(
            origen=Pedido.Origen.WHATSAPP, estado=Pedido.Estado.PENDIENTE_VALIDACION
        ).order_by('-creado_en')
        data = PedidoListaSerializer(queryset[:50], many=True, context=self.get_serializer_context()).data
        ultimo = super().get_queryset().order_by('-id').values_list('id', flat=True).first()
        return Response({'pendientes': data, 'total': queryset.count(), 'ultimo_id': ultimo or 0})
