from django.test import TestCase

from carta.models import Plato
from clientes.models import Cliente
from core.models import Usuario
from core.testing import cliente_api, crear_carta, crear_cliente, crear_restaurante, crear_usuario
from pedidos.models import Pedido
from pedidos.servicios import crear_pedido


class AislamientoTenantTests(TestCase):
    """Base y esquema compartidos: un restaurante nunca ve ni toca datos de otro."""

    def setUp(self):
        self.sabrosito = crear_restaurante('elsabrosito')
        self.rival = crear_restaurante('pollosrival')
        self.carta_sabrosito = crear_carta(self.sabrosito)
        self.carta_rival = crear_carta(self.rival)
        self.cliente_rival = crear_cliente(self.rival, telefono='51911111111')
        self.pedido_rival = crear_pedido(
            restaurante=self.rival, cliente=self.cliente_rival, items=[{'plato': self.carta_rival['entero'], 'cantidad': 1}]
        )
        self.api = cliente_api(crear_usuario(self.sabrosito))

    def test_listados_solo_muestran_datos_propios(self):
        for url, total in (('/api/v1/platos/', 3), ('/api/v1/categorias/', 2)):
            with self.subTest(url=url):
                data = self.api.get(url).json()
                self.assertEqual(len(data), total)
        ids_platos = {p['id'] for p in self.api.get('/api/v1/platos/').json()}
        self.assertTrue(ids_platos.isdisjoint({p.id for p in Plato.objects.filter(restaurante=self.rival)}))
        self.assertEqual(self.api.get('/api/v1/clientes/').json()['count'], 0)
        self.assertEqual(self.api.get('/api/v1/pedidos/').json()['count'], 0)

    def test_detalle_de_otro_restaurante_es_404(self):
        urls = (
            f'/api/v1/platos/{self.carta_rival["entero"].id}/',
            f'/api/v1/clientes/{self.cliente_rival.id}/',
            f'/api/v1/pedidos/{self.pedido_rival.id}/',
        )
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.api.get(url).status_code, 404)

    def test_no_puede_modificar_ni_borrar_datos_ajenos(self):
        plato = self.carta_rival['entero']
        self.assertEqual(self.api.patch(f'/api/v1/platos/{plato.id}/', {'precio': '1.00'}).status_code, 404)
        self.assertEqual(self.api.delete(f'/api/v1/clientes/{self.cliente_rival.id}/').status_code, 404)
        response = self.api.post(f'/api/v1/pedidos/{self.pedido_rival.id}/estado/', {'estado': 'cancelado'})
        self.assertEqual(response.status_code, 404)
        plato.refresh_from_db()
        self.assertEqual(str(plato.precio), '60.00')
        self.assertEqual(Pedido.objects.get(pk=self.pedido_rival.pk).estado, Pedido.Estado.PENDIENTE_VALIDACION)

    def test_crear_asigna_el_restaurante_del_usuario(self):
        response = self.api.post('/api/v1/clientes/', {'nombre': 'Ana', 'telefono': '976 543 210', 'restaurante': self.rival.id})
        self.assertEqual(response.status_code, 201)
        cliente = Cliente.objects.get(pk=response.json()['id'])
        self.assertEqual(cliente.restaurante, self.sabrosito)
        self.assertEqual(cliente.telefono, '51976543210')

    def test_no_acepta_referencias_a_objetos_de_otro_restaurante(self):
        response = self.api.post('/api/v1/platos/', {
            'categoria': self.carta_rival['pollos'].id, 'nombre': 'Intruso', 'precio': '10.00',
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('categoria', response.json())

        response = self.api.post('/api/v1/pedidos/', {
            'cliente_telefono': '51900000002',
            'items': [{'plato': self.carta_rival['entero'].id, 'cantidad': 1}],
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_mismo_telefono_puede_ser_cliente_de_dos_restaurantes(self):
        response = self.api.post('/api/v1/clientes/', {'nombre': 'Repetido', 'telefono': self.cliente_rival.telefono})
        self.assertEqual(response.status_code, 201)

    def test_usuarios_solo_del_mismo_restaurante(self):
        crear_usuario(self.rival, Usuario.Rol.CAJERO)
        usernames = {u['username'] for u in self.api.get('/api/v1/usuarios/').json()['results']}
        self.assertEqual(usernames, {'admin-elsabrosito'})

    def test_numeracion_de_pedidos_independiente_por_restaurante(self):
        pedido = crear_pedido(
            restaurante=self.sabrosito, cliente=crear_cliente(self.sabrosito),
            items=[{'plato': self.carta_sabrosito['entero'], 'cantidad': 1}],
        )
        self.assertEqual(pedido.numero, 1)
        self.assertEqual(self.pedido_rival.numero, 1)

    def test_no_borra_categoria_con_platos_ni_cliente_con_pedidos(self):
        categoria = self.carta_sabrosito['pollos']
        self.assertEqual(self.api.delete(f'/api/v1/categorias/{categoria.id}/').status_code, 400)
        cliente = crear_cliente(self.sabrosito, telefono='51922222222')
        crear_pedido(restaurante=self.sabrosito, cliente=cliente, items=[{'plato': self.carta_sabrosito['entero'], 'cantidad': 1}])
        self.assertEqual(self.api.delete(f'/api/v1/clientes/{cliente.id}/').status_code, 400)
