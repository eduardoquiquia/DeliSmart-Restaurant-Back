from datetime import timedelta
from unittest import mock

import requests
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from core.licencias import verificar_licencia
from core.models import Restaurante, Usuario
from core.testing import cliente_api, crear_restaurante, crear_usuario


class LoginTests(TestCase):
    def setUp(self):
        cache.clear()
        self.restaurante = crear_restaurante()
        self.user = crear_usuario(self.restaurante, Usuario.Rol.CAJERO, username='luis')
        self.user.email = 'luis@sabrosito.pe'
        self.user.save()
        self.api = APIClient()

    def login(self, username, password='clave-segura-123'):
        return self.api.post('/api/v1/auth/login/', {'username': username, 'password': password}, format='json')

    def test_login_con_usuario_o_correo(self):
        for identificador in ('luis', 'LUIS@sabrosito.pe'):
            with self.subTest(identificador=identificador):
                response = self.login(identificador)
                self.assertEqual(response.status_code, 200)
                self.api.credentials(HTTP_AUTHORIZATION=f"Bearer {response.json()['access']}")
                perfil = self.api.get('/api/v1/auth/me/').json()
                self.assertEqual(perfil['rol'], 'cajero')
                self.assertEqual(perfil['restaurante']['subdominio'], 'elsabrosito')
                self.api.credentials()

    def test_credenciales_incorrectas(self):
        self.assertEqual(self.login('luis', 'otra').status_code, 401)

    def test_usuario_sin_restaurante_no_entra(self):
        suelto = Usuario(username='suelto')
        suelto.set_password('clave-segura-123')
        suelto.save()
        self.assertEqual(self.login('suelto').status_code, 403)


class LicenciaPanelTests(TestCase):
    def test_licencia_vencida_bloquea_el_panel_pero_no_el_perfil(self):
        restaurante = crear_restaurante(dias_licencia=-1)
        api = cliente_api(crear_usuario(restaurante))
        response = api.get('/api/v1/platos/')
        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.json()['detail'], 'La licencia del restaurante venció.')

        perfil = api.get('/api/v1/auth/me/').json()
        self.assertFalse(perfil['licencia']['vigente'])

    def test_licencia_cancelada_bloquea(self):
        restaurante = crear_restaurante(licencia_estado=Restaurante.EstadoLicencia.CANCELADA)
        self.assertEqual(cliente_api(crear_usuario(restaurante)).get('/api/v1/pedidos/').status_code, 402)

    def test_licencia_activa_permite(self):
        restaurante = crear_restaurante()
        self.assertEqual(cliente_api(crear_usuario(restaurante)).get('/api/v1/pedidos/').status_code, 200)


@override_settings(ADMIN_SAAS_API_URL='http://admin.test', INTERNAL_API_TOKEN='secreto', LICENSE_CACHE_SECONDS=300)
class LicenciaAdminApiTests(TestCase):
    def setUp(self):
        self.restaurante = crear_restaurante(dias_licencia=-5)

    def respuesta(self, data, status=200):
        response = mock.Mock(status_code=status)
        response.json.return_value = data
        response.raise_for_status.return_value = None
        return response

    def test_consulta_al_admin_con_token_interno_y_guarda_cache(self):
        vence = (timezone.localdate() + timedelta(days=20)).isoformat()
        with mock.patch('core.licencias.requests.get', return_value=self.respuesta(
            {'estado': 'activa', 'plan': 'pro', 'fecha_vencimiento': vence}
        )) as get:
            resultado = verificar_licencia(self.restaurante)
            self.assertTrue(resultado.vigente)
            self.assertEqual(resultado.fuente, 'admin_api')
            url = get.call_args.args[0]
            self.assertEqual(url, 'http://admin.test/api/internal/licencias/elsabrosito/')
            self.assertEqual(get.call_args.kwargs['headers']['Authorization'], 'Bearer secreto')

            # La segunda consulta usa la copia guardada.
            self.assertEqual(verificar_licencia(self.restaurante).fuente, 'cache')
            self.assertEqual(get.call_count, 1)

    def test_admin_caido_usa_la_licencia_local(self):
        with mock.patch('core.licencias.requests.get', side_effect=requests.ConnectionError):
            resultado = verificar_licencia(self.restaurante)
        self.assertFalse(resultado.vigente)
        self.assertEqual(resultado.fuente, 'local')

    @override_settings(LICENSE_FALLBACK='deny')
    def test_admin_caido_con_fallback_deny_bloquea(self):
        self.restaurante.licencia_vencimiento = timezone.localdate() + timedelta(days=5)
        self.restaurante.save()
        with mock.patch('core.licencias.requests.get', side_effect=requests.ConnectionError):
            self.assertFalse(verificar_licencia(self.restaurante).vigente)


class RolesTests(TestCase):
    def setUp(self):
        self.restaurante = crear_restaurante()

    def test_cocina_no_ve_clientes_ni_reportes(self):
        api = cliente_api(crear_usuario(self.restaurante, Usuario.Rol.COCINA))
        self.assertEqual(api.get('/api/v1/clientes/').status_code, 403)
        self.assertEqual(api.get('/api/v1/reportes/resumen/').status_code, 403)
        self.assertEqual(api.get('/api/v1/pedidos/tablero/').status_code, 200)

    def test_solo_admin_gestiona_usuarios_y_configuracion(self):
        api = cliente_api(crear_usuario(self.restaurante, Usuario.Rol.CAJERO))
        self.assertEqual(api.get('/api/v1/usuarios/').status_code, 403)
        self.assertEqual(api.get('/api/v1/restaurante/').status_code, 200)
        self.assertEqual(api.patch('/api/v1/restaurante/', {'nombre': 'Otro'}).status_code, 403)

        admin = cliente_api(crear_usuario(self.restaurante, Usuario.Rol.ADMIN))
        response = admin.patch('/api/v1/restaurante/', {'radio_cobertura_km': '4.50', 'licencia_estado': 'activa'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['radio_cobertura_km'], '4.50')

    def test_admin_crea_personal_en_su_restaurante(self):
        admin = cliente_api(crear_usuario(self.restaurante, Usuario.Rol.ADMIN))
        response = admin.post('/api/v1/usuarios/', {
            'username': 'nuevo', 'rol': 'cocina', 'password': 'Brasa-segura-2026',
        })
        self.assertEqual(response.status_code, 201)
        nuevo = Usuario.objects.get(username='nuevo')
        self.assertEqual(nuevo.restaurante, self.restaurante)
        self.assertTrue(nuevo.check_password('Brasa-segura-2026'))
