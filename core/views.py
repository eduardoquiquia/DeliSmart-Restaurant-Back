from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import filters, generics, serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .licencias import verificar_licencia
from .models import Usuario as UsuarioModel
from .permissions import SoloAdmin
from .sso import TokenSSOInvalido, canjear_token
from .serializers import PerfilSerializer, RestauranteSerializer, UsuarioSerializer
from .tenancy import TenantViewSet, restaurante_de

Usuario = get_user_model()


class HealthView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({'status': 'ok'})


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()


class LoginView(APIView):
    """Login del personal con usuario o correo. Un usuario sin restaurante no entra al panel."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'

    def post(self, request):
        data = LoginSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        identifier = data.validated_data['username'].strip()
        user = (
            Usuario.objects.select_related('restaurante')
            .filter(Q(username__iexact=identifier) | Q(email__iexact=identifier))
            .first()
        )
        if not user or not user.is_active or not user.check_password(data.validated_data['password']):
            return Response({'detail': 'Usuario o contraseña incorrectos.'}, status=status.HTTP_401_UNAUTHORIZED)
        if user.restaurante is None:
            return Response({'detail': 'Tu usuario no pertenece a ninguna pollería.'}, status=status.HTTP_403_FORBIDDEN)
        return Response(tokens_para(user))


def tokens_para(user):
    refresh = RefreshToken.for_user(user)
    refresh['rol'] = user.rol
    refresh['restaurante'] = user.restaurante.subdominio
    return {'access': str(refresh.access_token), 'refresh': str(refresh)}


class SSOSerializer(serializers.Serializer):
    token = serializers.CharField()


class SSOView(APIView):
    """Canjea el enlace de un solo uso que genera "Mi Plan" en el panel admin por una sesión."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'

    def post(self, request):
        data = SSOSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            user = canjear_token(data.validated_data['token'])
        except TokenSSOInvalido as error:
            return Response({'detail': str(error)}, status=status.HTTP_401_UNAUTHORIZED)
        return Response(tokens_para(user))


class PerfilView(APIView):
    """Responde aunque la licencia venza, para que el panel muestre el motivo del bloqueo."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        resultado = verificar_licencia(restaurante_de(request))
        data = PerfilSerializer(request.user).data
        data['licencia'] = {
            'vigente': resultado.vigente,
            'estado': resultado.estado,
            'vencimiento': resultado.vencimiento,
            'fuente': resultado.fuente,
            'motivo': resultado.motivo,
        }
        data['integraciones_simuladas'] = settings.INTEGRATIONS_MOCK
        return Response(data)


class RestauranteView(generics.RetrieveUpdateAPIView):
    serializer_class = RestauranteSerializer

    def get_object(self):
        return restaurante_de(self.request)

    def get_permissions(self):
        permissions = super().get_permissions()
        if self.request.method not in ('GET', 'HEAD', 'OPTIONS'):
            permissions.append(SoloAdmin())
        return permissions


class UsuarioViewSet(TenantViewSet):
    queryset = Usuario.objects.order_by('rol', 'username')
    serializer_class = UsuarioSerializer
    roles_lectura = (UsuarioModel.Rol.ADMIN,)
    roles_escritura = (UsuarioModel.Rol.ADMIN,)
    filter_backends = [filters.SearchFilter]
    search_fields = ['username', 'first_name', 'last_name', 'email']

    def perform_destroy(self, instance):
        if instance == self.request.user:
            raise serializers.ValidationError({'detail': 'No puedes eliminar tu propio usuario.'})
        instance.delete()
