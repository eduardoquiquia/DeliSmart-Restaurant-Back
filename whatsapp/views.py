import json
import logging
import re

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from rest_framework import filters, serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Usuario
from core.permissions import RolPermitido
from core.tenancy import TenantReadOnlyViewSet, restaurante_de
from pedidos.models import Pedido

from .models import Conversacion, Mensaje
from .servicios import integraciones
from .servicios.cliente_whatsapp import firma_valida
from .servicios.mensajeria import enviar_mensaje
from .servicios.pipeline import Entrante, procesar_mensaje
from .servicios.webhook import procesar_payload

logger = logging.getLogger('delismart.webhook')

ATENCION = (Usuario.Rol.ADMIN, Usuario.Rol.CAJERO)
TELEFONO_SIMULADOR = '51900000001'


# --- Webhook de Meta -------------------------------------------------------------------------

@method_decorator(csrf_exempt, name='dispatch')
class WebhookView(View):
    """Endpoint público para Meta WhatsApp Cloud API.

    TODO(credenciales): registrar `https://<dominio>/api/whatsapp/webhook/` en el panel de Meta,
    con WHATSAPP_VERIFY_TOKEN, y suscribir el campo `messages`.
    """

    def get(self, request):
        mode = request.GET.get('hub.mode')
        token = request.GET.get('hub.verify_token')
        challenge = request.GET.get('hub.challenge', '')
        if mode == 'subscribe' and settings.WHATSAPP_VERIFY_TOKEN and token == settings.WHATSAPP_VERIFY_TOKEN:
            return HttpResponse(challenge, content_type='text/plain')
        return HttpResponse('Token de verificación inválido.', status=403)

    def post(self, request):
        cuerpo = request.body
        cabecera = request.headers.get('X-Hub-Signature-256')
        if settings.WHATSAPP_APP_SECRET:
            if not firma_valida(cuerpo, cabecera):
                return HttpResponse('Firma inválida.', status=403)
        elif not settings.INTEGRATIONS_MOCK:
            return HttpResponse('Falta WHATSAPP_APP_SECRET para validar la firma.', status=403)
        else:
            logger.warning('[simulado] Webhook aceptado sin verificar firma: falta WHATSAPP_APP_SECRET.')

        try:
            payload = json.loads(cuerpo or b'{}')
        except ValueError:
            return HttpResponse('JSON inválido.', status=400)

        # TODO(producción): mover a una cola (Celery/RQ) para responder a Meta en menos de 5 s.
        procesados = procesar_payload(payload)
        return JsonResponse({'procesados': procesados})


# --- Conversaciones ---------------------------------------------------------------------------

class MensajeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Mensaje
        fields = (
            'id', 'direccion', 'autor', 'tipo', 'texto', 'imagen', 'latitud', 'longitud',
            'estado_envio', 'creado_en',
        )


class ConversacionSerializer(serializers.ModelSerializer):
    cliente_nombre = serializers.CharField(source='cliente.nombre', read_only=True)
    cliente_id = serializers.IntegerField(source='cliente.id', read_only=True)
    ultimo_mensaje = serializers.SerializerMethodField()
    pedido_activo = serializers.SerializerMethodField()

    class Meta:
        model = Conversacion
        fields = (
            'id', 'telefono', 'cliente_id', 'cliente_nombre', 'estado', 'simulada', 'no_leidos',
            'ultimo_mensaje_en', 'ultimo_mensaje', 'pedido_activo', 'borrador', 'creado_en',
        )

    def get_ultimo_mensaje(self, conversacion):
        mensaje = conversacion.mensajes.order_by('-creado_en', '-id').first()
        if mensaje is None:
            return None
        return {'texto': mensaje.texto or f'[{mensaje.get_tipo_display()}]', 'direccion': mensaje.direccion}

    def get_pedido_activo(self, conversacion):
        pedido = (
            conversacion.pedidos.exclude(estado__in=(Pedido.Estado.ENTREGADO, Pedido.Estado.CANCELADO))
            .order_by('-creado_en').first()
        )
        return {'id': pedido.id, 'numero': pedido.numero, 'estado': pedido.estado} if pedido else None


class ConversacionViewSet(TenantReadOnlyViewSet):
    queryset = Conversacion.objects.select_related('cliente')
    serializer_class = ConversacionSerializer
    roles_lectura = ATENCION
    roles_escritura = ATENCION
    filter_backends = [filters.SearchFilter]
    search_fields = ['telefono', 'cliente__nombre']

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get('simuladas') == 'false':
            queryset = queryset.filter(simulada=False)
        return queryset

    @action(detail=True, methods=['post'])
    def estado(self, request, pk=None):
        """Alterna entre el asistente y la atención del personal."""
        conversacion = self.get_object()
        estado = request.data.get('estado')
        if estado not in Conversacion.Estado.values:
            return Response({'estado': 'Estado inválido.'}, status=400)
        conversacion.estado = estado
        conversacion.save(update_fields=['estado'])
        return Response(self.get_serializer(conversacion).data)

    @action(detail=True)
    def mensajes(self, request, pk=None):
        conversacion = self.get_object()
        desde = request.query_params.get('desde')
        mensajes = conversacion.mensajes.all()
        if desde and desde.isdigit():
            mensajes = mensajes.filter(id__gt=int(desde))
        if conversacion.no_leidos:
            Conversacion.objects.filter(pk=conversacion.pk).update(no_leidos=0)
        return Response(MensajeSerializer(mensajes, many=True, context={'request': request}).data)

    @action(detail=True, methods=['post'])
    def responder(self, request, pk=None):
        """El personal escribe en el chat; el asistente deja de responder solo."""
        conversacion = self.get_object()
        texto = (request.data.get('texto') or '').strip()
        if not texto:
            return Response({'texto': 'Escribe un mensaje.'}, status=400)
        conversacion.estado = Conversacion.Estado.HUMANO
        conversacion.save(update_fields=['estado'])
        mensaje = enviar_mensaje(conversacion, texto, autor=Mensaje.Autor.PERSONAL)
        return Response(MensajeSerializer(mensaje, context={'request': request}).data, status=201)


# --- Simulador --------------------------------------------------------------------------------

class SimuladorSerializer(serializers.Serializer):
    telefono = serializers.CharField(required=False, default=TELEFONO_SIMULADOR)
    nombre = serializers.CharField(required=False, allow_blank=True, default='Cliente de prueba')
    tipo = serializers.ChoiceField(choices=('texto', 'imagen', 'ubicacion'), default='texto')
    texto = serializers.CharField(required=False, allow_blank=True, default='')
    imagen = serializers.ImageField(required=False)
    latitud = serializers.FloatField(required=False, min_value=-90, max_value=90)
    longitud = serializers.FloatField(required=False, min_value=-180, max_value=180)
    direccion = serializers.CharField(required=False, allow_blank=True, default='')

    def validate_telefono(self, value):
        telefono = re.sub(r'\D', '', value)
        if len(telefono) < 8:
            raise serializers.ValidationError('Teléfono inválido.')
        return telefono

    def validate(self, attrs):
        tipo = attrs['tipo']
        if tipo == 'texto' and not attrs['texto'].strip():
            raise serializers.ValidationError({'texto': 'Escribe un mensaje.'})
        if tipo == 'imagen' and 'imagen' not in attrs:
            raise serializers.ValidationError({'imagen': 'Adjunta la captura del comprobante.'})
        if tipo == 'ubicacion' and ('latitud' not in attrs or 'longitud' not in attrs):
            raise serializers.ValidationError({'latitud': 'Indica latitud y longitud.'})
        return attrs


class SimuladorView(APIView):
    """Simulador de WhatsApp: un mensaje falso recorre el mismo pipeline que el webhook real."""

    permission_classes = APIView.permission_classes + [RolPermitido]
    roles_lectura = ATENCION
    roles_escritura = ATENCION

    def _conversacion(self, request, telefono):
        return Conversacion.objects.filter(restaurante=restaurante_de(request), telefono=telefono).first()

    def _respuesta(self, request, conversacion, extra=None):
        data = {
            'conversacion': ConversacionSerializer(conversacion).data if conversacion else None,
            'mensajes': MensajeSerializer(conversacion.mensajes.all(), many=True, context={'request': request}).data
            if conversacion else [],
            'integraciones': integraciones.estado(),
        }
        data.update(extra or {})
        return data

    def get(self, request):
        telefono = re.sub(r'\D', '', request.query_params.get('telefono', TELEFONO_SIMULADOR))
        return Response(self._respuesta(request, self._conversacion(request, telefono)))

    def post(self, request):
        serializer = SimuladorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        datos = serializer.validated_data
        imagen = datos.get('imagen')
        entrante = Entrante(
            telefono=datos['telefono'],
            nombre=datos['nombre'],
            tipo={'texto': Mensaje.Tipo.TEXTO, 'imagen': Mensaje.Tipo.IMAGEN, 'ubicacion': Mensaje.Tipo.UBICACION}[datos['tipo']],
            texto=datos['texto'],
            latitud=datos.get('latitud'),
            longitud=datos.get('longitud'),
            direccion=datos['direccion'],
            imagen=imagen,
            imagen_nombre=getattr(imagen, 'name', 'comprobante.jpg'),
        )
        resultado = procesar_mensaje(restaurante_de(request), entrante, simulada=True)
        if not resultado.procesado and resultado.conversacion is None:
            return Response({'detail': resultado.motivo}, status=status.HTTP_409_CONFLICT)
        pedido = {'id': resultado.pedido.id, 'numero': resultado.pedido.numero} if resultado.pedido else None
        return Response(self._respuesta(request, resultado.conversacion, {'pedido_creado': pedido}), status=201)

    def delete(self, request):
        """Reinicia el chat de prueba: borra la conversación simulada y su borrador."""
        telefono = re.sub(r'\D', '', request.query_params.get('telefono', TELEFONO_SIMULADOR))
        conversacion = self._conversacion(request, telefono)
        if conversacion and conversacion.simulada:
            with transaction.atomic():
                conversacion.pedidos.update(conversacion=None)
                conversacion.delete()
        return Response(status=204)


class IntegracionesView(APIView):
    def get(self, request):
        return Response(integraciones.estado())
