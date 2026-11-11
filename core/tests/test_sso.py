from datetime import timedelta
from unittest import mock

from django.core import signing
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Restaurante, Usuario
from core.sso import SSO_SALT
from core.testing import crear_restaurante, crear_usuario

URL = '/api/v1/auth/sso/'
TOKEN = 'token-interno-de-prueba'


def firmar(jti='abc123', subdominio='nuevapolleria', email='ana@example.com', estado='activa', dias=30):
    payload = {
        'jti': jti,
        'restaurante': {'subdominio': subdominio, 'nombre': 'Nueva Pollería', 'ruc': '20123456789', 'telefono': ''},
        'usuario': {'email': email, 'first_name': 'Ana', 'last_name': 'Pérez'},
        'licencia': {
            'estado': estado,
            'plan': 'pro',
            'fecha_vencimiento': (timezone.localdate() + timedelta(days=dias)).isoformat(),
        },
    }
    return signing.dumps(payload, key=TOKEN, salt=SSO_SALT)


@override_settings(INTERNAL_API_TOKEN=TOKEN, ADMIN_SAAS_API_URL='')
class SSOTests(TestCase):
    def canjear(self, token):
        return APIClient().post(URL, {'token': token}, format='json')

    def test_creates_restaurant_and_admin_and_logs_in(self):
        response = self.canjear(firmar())

        self.assertEqual(response.status_code, 200)
        restaurante = Restaurante.objects.get(subdominio='nuevapolleria')
        self.assertEqual(restaurante.ruc, '20123456789')
        self.assertTrue(restaurante.licencia_vigente)
        user = Usuario.objects.get(restaurante=restaurante)
        self.assertEqual((user.rol, user.email, user.username), ('admin', 'ana@example.com', 'ana'))
        self.assertFalse(user.has_usable_password())

        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}')
        me = api.get('/api/v1/auth/me/')
        self.assertEqual(me.status_code, 200)
        self.assertTrue(me.data['licencia']['vigente'])
        self.assertEqual(api.get('/api/v1/usuarios/').status_code, 200)

    def test_links_existing_user_by_email(self):
        restaurante = crear_restaurante('nuevapolleria')
        user = crear_usuario(restaurante, rol=Usuario.Rol.CAJERO, username='ana-caja')
        user.email = 'ANA@example.com'
        user.save()

        self.assertEqual(self.canjear(firmar()).status_code, 200)

        self.assertEqual(Usuario.objects.filter(restaurante=restaurante).count(), 1)
        user.refresh_from_db()
        self.assertEqual(user.rol, Usuario.Rol.ADMIN)
        self.assertTrue(user.has_usable_password())

    def test_second_visit_reuses_admin(self):
        self.canjear(firmar('uno'))
        self.canjear(firmar('dos'))
        self.assertEqual(Usuario.objects.filter(restaurante__subdominio='nuevapolleria').count(), 1)

    def test_username_taken_in_other_restaurant(self):
        crear_usuario(crear_restaurante('otra'), username='ana')
        self.canjear(firmar())
        self.assertTrue(Usuario.objects.filter(username='ana-2', restaurante__subdominio='nuevapolleria').exists())

    def test_link_is_single_use(self):
        token = firmar()
        self.assertEqual(self.canjear(token).status_code, 200)
        self.assertEqual(self.canjear(token).status_code, 401)

    def test_rejects_tampered_or_foreign_signature(self):
        self.assertEqual(self.canjear(firmar() + 'x').status_code, 401)
        ajeno = signing.dumps({'jti': 'x', 'restaurante': {'subdominio': 'a'}}, key='otra-clave', salt=SSO_SALT)
        self.assertEqual(self.canjear(ajeno).status_code, 401)
        self.assertFalse(Restaurante.objects.exists())

    @override_settings(SSO_MAX_AGE_SECONDS=60)
    def test_rejects_expired_link(self):
        token = firmar()
        later = timezone.now().timestamp() + 120
        with mock.patch('django.core.signing.time.time', return_value=later):
            response = self.canjear(token)
        self.assertEqual(response.status_code, 401)
        self.assertIn('venció', response.data['detail'])

    def test_expired_license_logs_in_but_panel_is_blocked(self):
        response = self.canjear(firmar(estado='vencida'))
        self.assertEqual(response.status_code, 200)
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}')
        self.assertEqual(api.get('/api/v1/pedidos/').status_code, 402)

    @override_settings(INTERNAL_API_TOKEN='')
    def test_without_shared_token(self):
        self.assertEqual(self.canjear('cualquiera').status_code, 401)
