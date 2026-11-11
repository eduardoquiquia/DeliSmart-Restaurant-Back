from django.db.models import Count
from rest_framework import filters, serializers

from core.models import Usuario
from core.tenancy import TenantPrimaryKeyRelatedField, TenantViewSet

from .models import Categoria, Plato

TODOS = tuple(Usuario.Rol.values)


class CategoriaSerializer(serializers.ModelSerializer):
    total_platos = serializers.IntegerField(read_only=True)

    class Meta:
        model = Categoria
        fields = ('id', 'nombre', 'descripcion', 'orden', 'activa', 'total_platos')

    def validate_nombre(self, value):
        request = self.context['request']
        repetida = Categoria.objects.filter(restaurante=request.user.restaurante, nombre__iexact=value)
        if self.instance:
            repetida = repetida.exclude(pk=self.instance.pk)
        if repetida.exists():
            raise serializers.ValidationError('Ya existe una categoría con ese nombre.')
        return value


class PlatoSerializer(serializers.ModelSerializer):
    categoria = TenantPrimaryKeyRelatedField(queryset=Categoria.objects.all())
    categoria_nombre = serializers.CharField(source='categoria.nombre', read_only=True)

    class Meta:
        model = Plato
        fields = (
            'id', 'categoria', 'categoria_nombre', 'nombre', 'descripcion', 'precio', 'imagen',
            'disponible', 'alias', 'creado_en', 'actualizado_en',
        )
        read_only_fields = ('id', 'creado_en', 'actualizado_en')

    def validate_precio(self, value):
        if value <= 0:
            raise serializers.ValidationError('El precio debe ser mayor a cero.')
        return value


class CategoriaViewSet(TenantViewSet):
    queryset = Categoria.objects.annotate(total_platos=Count('platos'))
    serializer_class = CategoriaSerializer
    roles_lectura = TODOS
    pagination_class = None


class PlatoViewSet(TenantViewSet):
    queryset = Plato.objects.select_related('categoria')
    serializer_class = PlatoSerializer
    roles_lectura = TODOS
    # La cocina marca platos agotados durante el turno.
    roles_escritura = (Usuario.Rol.ADMIN, Usuario.Rol.COCINA)
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['nombre', 'descripcion', 'categoria__nombre']
    ordering_fields = ['nombre', 'precio']
    pagination_class = None

    def get_queryset(self):
        queryset = super().get_queryset()
        categoria = self.request.query_params.get('categoria')
        disponible = self.request.query_params.get('disponible')
        if categoria:
            queryset = queryset.filter(categoria_id=categoria)
        if disponible in ('true', 'false'):
            queryset = queryset.filter(disponible=disponible == 'true')
        return queryset

    def check_permissions(self, request):
        super().check_permissions(request)
        # La cocina solo cambia la disponibilidad; crear, borrar o reprecificar es del admin.
        if request.user.rol == Usuario.Rol.COCINA and request.method not in ('GET', 'HEAD', 'OPTIONS'):
            campos = set(request.data.keys())
            if request.method != 'PATCH' or not campos or campos - {'disponible'}:
                self.permission_denied(request, message='La cocina solo puede cambiar la disponibilidad.')
