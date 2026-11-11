from decimal import Decimal

from django.test import TestCase

from core.models import Usuario
from core.testing import cliente_api, crear_carta, crear_cliente, crear_restaurante, crear_usuario
from pedidos.models import Pedido
from pedidos.servicios import crear_pedido


class ResumenTests(TestCase):
    def setUp(self):
        self.restaurante = crear_restaurante()
        carta = crear_carta(self.restaurante)
        cliente = crear_cliente(self.restaurante)
        for cantidad, origen in ((2, 'whatsapp'), (1, 'manual')):
            crear_pedido(restaurante=self.restaurante, cliente=cliente, origen=origen,
                         items=[{'plato': carta['entero'], 'cantidad': cantidad}])
        cancelado = crear_pedido(restaurante=self.restaurante, cliente=cliente, items=[{'plato': carta['gaseosa'], 'cantidad': 5}])
        Pedido.objects.filter(pk=cancelado.pk).update(estado='cancelado')
        # Otro restaurante no debe contar.
        rival = crear_restaurante('rival')
        crear_pedido(restaurante=rival, cliente=crear_cliente(rival), items=[{'plato': crear_carta(rival)['entero'], 'cantidad': 9}])

    def test_resumen_de_ventas_y_productos(self):
        data = cliente_api(crear_usuario(self.restaurante, Usuario.Rol.CAJERO)).get('/api/v1/reportes/resumen/').json()
        self.assertEqual(data['pedidos_total'], 2)
        self.assertEqual(Decimal(data['ventas_total']), Decimal('190.00'))
        self.assertEqual(data['por_origen'], {'whatsapp': 1, 'manual': 1})
        self.assertEqual(data['por_estado']['cancelado'], 1)
        self.assertEqual(data['productos_top'][0]['nombre'], 'Pollo a la brasa entero')
        self.assertEqual(data['productos_top'][0]['cantidad'], 3)
        self.assertEqual(Decimal(data['productos_top'][0]['ingresos']), Decimal('180.00'))
        self.assertEqual(len(data['serie_diaria']), 7)
