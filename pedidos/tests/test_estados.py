from decimal import Decimal

from django.test import TestCase

from core.models import Usuario
from core.testing import cliente_api, crear_carta, crear_cliente, crear_restaurante, crear_usuario
from pedidos.models import Pedido
from pedidos.servicios import crear_pedido


class EstadosPedidoTests(TestCase):
    def setUp(self):
        self.restaurante = crear_restaurante()
        self.carta = crear_carta(self.restaurante)
        self.cliente = crear_cliente(self.restaurante)
        self.cajero = crear_usuario(self.restaurante, Usuario.Rol.CAJERO)
        self.api = cliente_api(self.cajero)

    def pedido(self, origen=Pedido.Origen.WHATSAPP, porcentaje=100):
        return crear_pedido(
            restaurante=self.restaurante, cliente=self.cliente, origen=origen, porcentaje_adelanto=porcentaje,
            items=[{'plato': self.carta['entero'], 'cantidad': 2}, {'plato': self.carta['gaseosa'], 'cantidad': 1}],
        )

    def cambiar(self, pedido, estado, api=None):
        return (api or self.api).post(f'/api/v1/pedidos/{pedido.id}/estado/', {'estado': estado})

    def test_totales_y_adelanto(self):
        pedido = self.pedido(porcentaje=50)
        self.assertEqual(pedido.subtotal, Decimal('130.00'))
        self.assertEqual(pedido.total, Decimal('135.00'))
        self.assertEqual(pedido.monto_adelanto, Decimal('67.50'))
        self.assertEqual(pedido.saldo_pendiente, Decimal('67.50'))
        self.assertEqual(pedido.estado, Pedido.Estado.PENDIENTE_VALIDACION)

    def test_flujo_completo_con_confirmacion_de_pago(self):
        pedido = self.pedido()
        response = self.api.post(f'/api/v1/pedidos/{pedido.id}/confirmar-pago/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['estado'], 'en_preparacion')
        self.assertTrue(response.json()['pago_confirmado'])

        self.assertEqual(self.cambiar(pedido, 'en_camino').json()['estado'], 'en_camino')
        data = self.cambiar(pedido, 'entregado').json()
        self.assertEqual(data['estado'], 'entregado')
        self.assertEqual(
            [h['estado'] for h in self.api.get(f'/api/v1/pedidos/{pedido.id}/').json()['historial']],
            ['pendiente_validacion', 'en_preparacion', 'en_camino', 'entregado'],
        )

    def test_whatsapp_no_pasa_a_cocina_sin_confirmar_pago(self):
        pedido = self.pedido()
        response = self.cambiar(pedido, 'en_preparacion')
        self.assertEqual(response.status_code, 400)
        self.assertIn('confirma el pago', response.json()['estado'])

    def test_pedido_manual_pasa_directo_a_cocina(self):
        self.assertEqual(self.cambiar(self.pedido(origen=Pedido.Origen.MANUAL), 'en_preparacion').status_code, 200)

    def test_transiciones_invalidas(self):
        pedido = self.pedido()
        self.assertEqual(self.cambiar(pedido, 'entregado').status_code, 400)
        self.assertEqual(self.cambiar(pedido, 'en_camino').status_code, 400)

        self.cambiar(pedido, 'cancelado')
        for estado in ('pendiente_validacion', 'en_preparacion', 'entregado'):
            with self.subTest(estado=estado):
                self.assertEqual(self.cambiar(pedido, estado).status_code, 400)

    def test_no_se_cancela_un_pedido_en_camino(self):
        pedido = self.pedido(origen=Pedido.Origen.MANUAL)
        self.cambiar(pedido, 'en_preparacion')
        self.cambiar(pedido, 'en_camino')
        self.assertEqual(self.cambiar(pedido, 'cancelado').status_code, 400)

    def test_confirmar_pago_solo_en_pendientes(self):
        pedido = self.pedido()
        self.api.post(f'/api/v1/pedidos/{pedido.id}/confirmar-pago/')
        self.assertEqual(self.api.post(f'/api/v1/pedidos/{pedido.id}/confirmar-pago/').status_code, 400)

    def test_cocina_solo_despacha(self):
        cocina = cliente_api(crear_usuario(self.restaurante, Usuario.Rol.COCINA))
        pedido = self.pedido()
        self.assertEqual(cocina.post(f'/api/v1/pedidos/{pedido.id}/confirmar-pago/').status_code, 403)
        self.api.post(f'/api/v1/pedidos/{pedido.id}/confirmar-pago/')
        self.assertEqual(self.cambiar(pedido, 'cancelado', cocina).status_code, 403)
        self.assertEqual(self.cambiar(pedido, 'en_camino', cocina).status_code, 200)

    def test_cajero_registra_pedido_manual(self):
        response = self.api.post('/api/v1/pedidos/', {
            'cliente_telefono': '976 000 111',
            'cliente_nombre': 'Pedro',
            'items': [{'plato': self.carta['cuarto'].id, 'cantidad': 3}],
            'direccion_entrega': 'Av. Larco 100',
        }, format='json')
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['origen'], 'manual')
        self.assertEqual(data['total'], '59.00')
        self.assertEqual(data['cliente']['telefono'], '51976000111')

    def test_tablero_agrupa_por_estado(self):
        self.pedido()
        manual = self.pedido(origen=Pedido.Origen.MANUAL)
        self.cambiar(manual, 'en_preparacion')
        data = self.api.get('/api/v1/pedidos/tablero/').json()
        self.assertEqual(len(data['pendiente_validacion']), 1)
        self.assertEqual(len(data['en_preparacion']), 1)

    def test_polling_de_nuevos_pedidos_whatsapp(self):
        self.pedido()
        self.pedido(origen=Pedido.Origen.MANUAL)
        data = self.api.get('/api/v1/pedidos/nuevos/').json()
        self.assertEqual(data['total'], 1)
        self.assertEqual(data['pendientes'][0]['origen'], 'whatsapp')
        self.assertGreater(data['ultimo_id'], 0)
