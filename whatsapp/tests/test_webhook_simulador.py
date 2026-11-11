import hashlib
import hmac
import io
import json
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from core.models import Restaurante, Usuario
from core.testing import cliente_api, crear_carta, crear_restaurante, crear_usuario
from pedidos.models import Pedido
from whatsapp.models import Conversacion, Mensaje
from whatsapp.servicios.cliente_whatsapp import firma_valida

SECRETO = 'app-secret-de-prueba'
WEBHOOK = '/api/whatsapp/webhook/'


def payload_texto(texto, telefono='51987654321', wa_id='wamid.1', phone_number_id='1234567890'):
    return {
        'object': 'whatsapp_business_account',
        'entry': [{
            'id': 'WABA',
            'changes': [{
                'field': 'messages',
                'value': {
                    'messaging_product': 'whatsapp',
                    'metadata': {'display_phone_number': '51987111222', 'phone_number_id': phone_number_id},
                    'contacts': [{'wa_id': telefono, 'profile': {'name': 'María'}}],
                    'messages': [{'from': telefono, 'id': wa_id, 'type': 'text', 'text': {'body': texto}}],
                },
            }],
        }],
    }


def firmar(cuerpo, secreto=SECRETO):
    return 'sha256=' + hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()


def imagen_png():
    buffer = io.BytesIO()
    Image.new('RGB', (20, 20), 'purple').save(buffer, 'PNG')
    return SimpleUploadedFile('yape.png', buffer.getvalue(), content_type='image/png')


class FirmaTests(TestCase):
    def test_firma_valida_e_invalida(self):
        cuerpo = b'{"hola": 1}'
        self.assertTrue(firma_valida(cuerpo, firmar(cuerpo), SECRETO))
        self.assertFalse(firma_valida(cuerpo, firmar(cuerpo, 'otro'), SECRETO))
        self.assertFalse(firma_valida(cuerpo + b' ', firmar(cuerpo), SECRETO))
        self.assertFalse(firma_valida(cuerpo, None, SECRETO))
        self.assertFalse(firma_valida(cuerpo, 'md5=abc', SECRETO))
        self.assertFalse(firma_valida(cuerpo, firmar(cuerpo), ''))


@override_settings(WHATSAPP_APP_SECRET=SECRETO, WHATSAPP_VERIFY_TOKEN='verificame', INTEGRATIONS_MOCK=True)
class WebhookTests(TestCase):
    def setUp(self):
        self.restaurante = crear_restaurante(whatsapp_phone_number_id='1234567890')
        crear_carta(self.restaurante)

    def post(self, payload, firma=None):
        cuerpo = json.dumps(payload).encode()
        return self.client.post(
            WEBHOOK, cuerpo, content_type='application/json',
            HTTP_X_HUB_SIGNATURE_256=firma if firma is not None else firmar(cuerpo),
        )

    def test_verificacion_get(self):
        ok = self.client.get(WEBHOOK, {'hub.mode': 'subscribe', 'hub.verify_token': 'verificame', 'hub.challenge': '42'})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.content, b'42')
        mal = self.client.get(WEBHOOK, {'hub.mode': 'subscribe', 'hub.verify_token': 'otro', 'hub.challenge': '42'})
        self.assertEqual(mal.status_code, 403)

    def test_rechaza_firma_invalida(self):
        response = self.post(payload_texto('hola'), firma='sha256=deadbeef')
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Mensaje.objects.exists())

    def test_mensaje_firmado_crea_conversacion_y_respuesta(self):
        response = self.post(payload_texto('hola, quiero ver la carta'))
        self.assertEqual(response.status_code, 200)
        conversacion = Conversacion.objects.get(restaurante=self.restaurante, telefono='51987654321')
        self.assertEqual(conversacion.cliente.nombre, 'María')
        mensajes = list(conversacion.mensajes.values_list('direccion', flat=True))
        self.assertEqual(mensajes[0], 'entrante')
        self.assertIn('saliente', mensajes)
        self.assertTrue(conversacion.mensajes.filter(texto__contains='Pollo a la brasa entero').exists())

    def test_reintento_de_meta_no_duplica(self):
        self.post(payload_texto('hola'))
        self.post(payload_texto('hola'))
        self.assertEqual(Mensaje.objects.filter(direccion='entrante').count(), 1)

    def test_licencia_vencida_ignora_mensajes(self):
        self.restaurante.licencia_estado = Restaurante.EstadoLicencia.VENCIDA
        self.restaurante.save()
        self.assertEqual(self.post(payload_texto('hola')).json()['procesados'], 0)
        self.assertFalse(Mensaje.objects.exists())

    @override_settings(WHATSAPP_APP_SECRET='', INTEGRATIONS_MOCK=False)
    def test_sin_app_secret_en_modo_real_rechaza(self):
        self.assertEqual(self.post(payload_texto('hola'), firma='').status_code, 403)


MEDIA_TEMPORAL = tempfile.mkdtemp(prefix='delismart-media-')


@override_settings(INTEGRATIONS_MOCK=True, MEDIA_ROOT=MEDIA_TEMPORAL)
class SimuladorTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_TEMPORAL, ignore_errors=True)

    def setUp(self):
        self.restaurante = crear_restaurante(radio_cobertura_km=5)
        self.carta = crear_carta(self.restaurante)
        self.api = cliente_api(crear_usuario(self.restaurante, Usuario.Rol.CAJERO))

    def enviar(self, **datos):
        formato = 'multipart' if 'imagen' in datos else 'json'
        return self.api.post('/api/v1/simulador/', datos, format=formato)

    def test_flujo_completo_crea_pedido_real_en_el_panel(self):
        self.assertEqual(self.enviar(texto='Hola').status_code, 201)
        response = self.enviar(texto='Quiero 2 pollo entero y una inca kola')
        borrador = response.json()['conversacion']['borrador']
        self.assertEqual({i['nombre']: i['cantidad'] for i in borrador['items']},
                         {'Pollo a la brasa entero': 2, 'Inca Kola 1.5L': 1})

        response = self.enviar(tipo='ubicacion', latitud=-12.1225, longitud=-77.0301, direccion='Av. Larco 345')
        self.assertTrue(any('km' in m['texto'] for m in response.json()['mensajes'] if m['direccion'] == 'saliente'))

        self.enviar(texto='Pago con yape, adelanto del 50%')
        response = self.enviar(tipo='imagen', imagen=imagen_png())
        self.assertEqual(response.status_code, 201)
        creado = response.json()['pedido_creado']
        self.assertIsNotNone(creado)

        pedido = Pedido.objects.get(pk=creado['id'])
        self.assertEqual(pedido.restaurante, self.restaurante)
        self.assertEqual(pedido.origen, 'whatsapp')
        self.assertEqual(pedido.estado, 'pendiente_validacion')
        self.assertEqual(pedido.metodo_pago, 'yape')
        self.assertEqual(pedido.porcentaje_adelanto, 50)
        self.assertEqual(str(pedido.total), '135.00')
        self.assertEqual(str(pedido.monto_adelanto), '67.50')
        self.assertTrue(pedido.comprobante)
        self.assertIsNotNone(pedido.distancia_km)
        self.assertEqual(pedido.tiempo_estimado_min, self.restaurante.tiempo_preparacion_min + pedido.tiempo_traslado_min)
        self.assertTrue(pedido.conversacion.simulada)

        # El pedido aparece en el polling del cajero y el borrador queda limpio.
        nuevos = self.api.get('/api/v1/pedidos/nuevos/').json()
        self.assertEqual(nuevos['pendientes'][0]['id'], pedido.id)
        self.assertEqual(pedido.conversacion.borrador, {'items': []})

        # Al confirmar el pago, el cliente recibe el aviso en el chat.
        with self.captureOnCommitCallbacks(execute=True):
            self.api.post(f'/api/v1/pedidos/{pedido.id}/confirmar-pago/')
        ultimo = pedido.conversacion.mensajes.order_by('-id').first()
        self.assertIn('en preparación', ultimo.texto)

    def test_fuera_de_cobertura_no_crea_pedido(self):
        self.enviar(texto='1 pollo entero')
        # Callao, a más de 5 km de Miraflores.
        response = self.enviar(tipo='ubicacion', latitud=-12.0566, longitud=-77.1181)
        self.assertTrue(response.json()['conversacion']['borrador']['fuera_de_cobertura'])
        self.enviar(texto='yape 100%')
        response = self.enviar(tipo='imagen', imagen=imagen_png())
        self.assertIsNone(response.json()['pedido_creado'])
        self.assertFalse(Pedido.objects.exists())

    def test_reiniciar_chat_de_prueba(self):
        self.enviar(texto='Hola')
        self.assertEqual(self.api.delete('/api/v1/simulador/').status_code, 204)
        self.assertFalse(Conversacion.objects.exists())

    def test_cocina_no_usa_el_simulador(self):
        cocina = cliente_api(crear_usuario(self.restaurante, Usuario.Rol.COCINA))
        self.assertEqual(cocina.post('/api/v1/simulador/', {'texto': 'hola'}).status_code, 403)

    def test_respuesta_del_personal_pausa_el_asistente(self):
        self.enviar(texto='Hola')
        conversacion = Conversacion.objects.get()
        self.api.post(f'/api/v1/conversaciones/{conversacion.id}/responder/', {'texto': 'Te atiende Luis'})
        antes = conversacion.mensajes.count()
        self.enviar(texto='carta')
        self.assertEqual(conversacion.mensajes.count(), antes + 1)  # Solo el mensaje del cliente.
