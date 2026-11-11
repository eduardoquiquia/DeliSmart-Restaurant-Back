from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import Avg, Count, F, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Usuario
from core.permissions import RolPermitido
from core.tenancy import restaurante_de
from inventario.models import Insumo
from pedidos.models import ItemPedido, Pedido

MAX_DIAS = 366


def _rango(params):
    hoy = timezone.localdate()
    try:
        hasta = datetime.strptime(params.get('hasta', ''), '%Y-%m-%d').date()
    except ValueError:
        hasta = hoy
    try:
        desde = datetime.strptime(params.get('desde', ''), '%Y-%m-%d').date()
    except ValueError:
        desde = hasta - timedelta(days=6)
    if desde > hasta:
        desde, hasta = hasta, desde
    desde = max(desde, hasta - timedelta(days=MAX_DIAS))
    return desde, hasta


class ResumenView(APIView):
    """Ventas, pedidos y productos más vendidos en un rango de fechas (por defecto, 7 días)."""

    permission_classes = APIView.permission_classes + [RolPermitido]
    roles_lectura = (Usuario.Rol.ADMIN, Usuario.Rol.CAJERO)

    def get(self, request):
        restaurante = restaurante_de(request)
        desde, hasta = _rango(request.query_params)
        pedidos = Pedido.objects.filter(restaurante=restaurante, creado_en__date__gte=desde, creado_en__date__lte=hasta)
        validos = pedidos.exclude(estado=Pedido.Estado.CANCELADO)
        entregados = pedidos.filter(estado=Pedido.Estado.ENTREGADO)

        totales = validos.aggregate(ventas=Sum('total'), ticket=Avg('total'), pedidos=Count('id'))
        por_estado = dict(pedidos.values_list('estado').annotate(n=Count('id')))
        por_origen = dict(validos.values_list('origen').annotate(n=Count('id')))

        dias = {
            fila['dia']: fila
            for fila in validos.annotate(dia=TruncDate('creado_en')).values('dia')
            .annotate(ventas=Sum('total'), pedidos=Count('id'))
        }
        serie = []
        dia = desde
        while dia <= hasta:
            fila = dias.get(dia, {})
            serie.append({'fecha': dia, 'ventas': fila.get('ventas') or Decimal('0'), 'pedidos': fila.get('pedidos', 0)})
            dia += timedelta(days=1)

        top = (
            ItemPedido.objects.filter(pedido__in=validos)
            .values('nombre')
            .annotate(cantidad=Sum('cantidad'), ingresos=Sum(F('cantidad') * F('precio_unitario')))
            .order_by('-cantidad', 'nombre')[:8]
        )

        hoy = timezone.localdate()
        hoy_qs = Pedido.objects.filter(restaurante=restaurante, creado_en__date=hoy)
        return Response({
            'desde': desde,
            'hasta': hasta,
            'ventas_total': totales['ventas'] or Decimal('0'),
            'ventas_cobradas': entregados.aggregate(v=Sum('total'))['v'] or Decimal('0'),
            'pedidos_total': totales['pedidos'],
            'ticket_promedio': (totales['ticket'] or Decimal('0')).quantize(Decimal('0.01')),
            'por_estado': {estado: por_estado.get(estado, 0) for estado in Pedido.Estado.values},
            'por_origen': {origen: por_origen.get(origen, 0) for origen in Pedido.Origen.values},
            'serie_diaria': serie,
            'productos_top': list(top),
            'hoy': {
                'pedidos': hoy_qs.exclude(estado=Pedido.Estado.CANCELADO).count(),
                'ventas': hoy_qs.exclude(estado=Pedido.Estado.CANCELADO).aggregate(v=Sum('total'))['v'] or Decimal('0'),
                'por_validar': hoy_qs.filter(estado=Pedido.Estado.PENDIENTE_VALIDACION).count(),
                'en_cocina': Pedido.objects.filter(restaurante=restaurante, estado=Pedido.Estado.EN_PREPARACION).count(),
                'en_camino': Pedido.objects.filter(restaurante=restaurante, estado=Pedido.Estado.EN_CAMINO).count(),
            },
            'insumos_bajo_stock': Insumo.objects.filter(restaurante=restaurante, stock__lte=F('stock_minimo')).count(),
        })
