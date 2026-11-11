from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import Restaurante

Usuario = get_user_model()


class RestauranteSerializer(serializers.ModelSerializer):
    licencia_vigente = serializers.BooleanField(read_only=True)

    class Meta:
        model = Restaurante
        fields = (
            'id', 'nombre', 'subdominio', 'ruc', 'telefono', 'logo',
            'direccion', 'latitud', 'longitud', 'radio_cobertura_km', 'tiempo_preparacion_min', 'costo_delivery',
            'yape_numero', 'yape_titular', 'plin_numero', 'plin_titular',
            'transferencia_banco', 'transferencia_cuenta', 'transferencia_cci', 'transferencia_titular',
            'whatsapp_numero', 'whatsapp_phone_number_id', 'mensaje_bienvenida', 'bot_activo',
            'licencia_estado', 'licencia_plan', 'licencia_vencimiento', 'licencia_vigente',
        )
        # El subdominio y la licencia los gobierna el backend admin.
        read_only_fields = (
            'id', 'subdominio', 'licencia_estado', 'licencia_plan', 'licencia_vencimiento', 'licencia_vigente',
        )

    def validate_radio_cobertura_km(self, value):
        if value <= 0 or value > 50:
            raise serializers.ValidationError('El radio de cobertura debe estar entre 0 y 50 km.')
        return value


class PerfilSerializer(serializers.ModelSerializer):
    nombre = serializers.SerializerMethodField()
    restaurante = serializers.SerializerMethodField()

    class Meta:
        model = Usuario
        fields = ('id', 'username', 'email', 'first_name', 'last_name', 'nombre', 'rol', 'restaurante')

    def get_nombre(self, user):
        return user.get_full_name() or user.username

    def get_restaurante(self, user):
        restaurante = user.restaurante
        if restaurante is None:
            return None
        return {'id': restaurante.id, 'nombre': restaurante.nombre, 'subdominio': restaurante.subdominio}


class UsuarioSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, min_length=8)

    class Meta:
        model = Usuario
        fields = (
            'id', 'username', 'email', 'first_name', 'last_name', 'telefono', 'rol', 'is_active',
            'password', 'last_login', 'date_joined',
        )
        read_only_fields = ('id', 'last_login', 'date_joined')

    def validate_password(self, value):
        validate_password(value)
        return value

    def validate(self, attrs):
        if self.instance is None and not attrs.get('password'):
            raise serializers.ValidationError({'password': 'La contraseña es obligatoria.'})
        return attrs

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = Usuario(**validated_data)
        user.set_password(password)
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance
