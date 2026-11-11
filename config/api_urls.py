from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from carta.views import CategoriaViewSet, PlatoViewSet
from clientes.views import ClienteViewSet
from core.views import HealthView, LoginView, PerfilView, RestauranteView, UsuarioViewSet
from inventario.views import InsumoViewSet
from pedidos.views import PedidoViewSet
from reportes.views import ResumenView
from whatsapp.views import ConversacionViewSet, IntegracionesView, SimuladorView

router = DefaultRouter()
router.register('categorias', CategoriaViewSet, basename='categoria')
router.register('platos', PlatoViewSet, basename='plato')
router.register('clientes', ClienteViewSet, basename='cliente')
router.register('insumos', InsumoViewSet, basename='insumo')
router.register('usuarios', UsuarioViewSet, basename='usuario')
router.register('pedidos', PedidoViewSet, basename='pedido')
router.register('conversaciones', ConversacionViewSet, basename='conversacion')

urlpatterns = [
    path('health/', HealthView.as_view()),
    path('auth/login/', LoginView.as_view()),
    path('auth/refresh/', TokenRefreshView.as_view()),
    path('auth/me/', PerfilView.as_view()),
    path('restaurante/', RestauranteView.as_view()),
    path('reportes/resumen/', ResumenView.as_view()),
    path('integraciones/', IntegracionesView.as_view()),
    path('simulador/', SimuladorView.as_view()),
    *router.urls,
]
