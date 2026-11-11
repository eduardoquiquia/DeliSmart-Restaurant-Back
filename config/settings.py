"""Configuración del backend de la pollería (panel del restaurante y canal de WhatsApp)."""

import os
from datetime import timedelta
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / '.env')


def env_list(name, default=''):
    return [item.strip() for item in os.environ.get(name, default).split(',') if item.strip()]


def env_bool(name, default='false'):
    return os.environ.get(name, default).strip().lower() in ('1', 'true', 'yes')


SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', '')
DEBUG = env_bool('DJANGO_DEBUG', 'true')

# La clave firma los JWT del personal: fuera de desarrollo no puede ser pública.
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured('DJANGO_SECRET_KEY es obligatoria con DJANGO_DEBUG=false.')
    SECRET_KEY = 'django-insecure-restaurante-solo-desarrollo-9v#2m!q7x@k4p8w&z1r6t3y5u0'

ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1')


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'rest_framework_simplejwt',
    'core',
    'carta',
    'clientes',
    'inventario',
    'pedidos',
    'whatsapp',
    'reportes',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Base de datos: solo PostgreSQL de Neon (base y esquema compartidos entre restaurantes).

DATABASE_URL = os.environ.get('DATABASE_URL', '')
if not DATABASE_URL.startswith(('postgres://', 'postgresql://')):
    raise ImproperlyConfigured('DATABASE_URL debe ser la cadena de conexión PostgreSQL de Neon.')

DATABASES = {
    'default': dj_database_url.parse(DATABASE_URL, conn_max_age=60, conn_health_checks=True),
}

AUTH_USER_MODEL = 'core.Usuario'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'es-pe'
TIME_ZONE = 'America/Lima'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
PUBLIC_BASE_URL = os.environ.get('PUBLIC_BASE_URL', 'http://localhost:8001').rstrip('/')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# CORS

CORS_ALLOWED_ORIGINS = env_list('CORS_ALLOWED_ORIGINS', 'http://localhost:5174,https://app.delismart.com')


# Django REST Framework

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ['rest_framework_simplejwt.authentication.JWTAuthentication'],
    # Todo el panel exige sesión y una licencia vigente; las vistas públicas lo sobrescriben.
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
        'core.permissions.LicenciaVigente',
    ],
    'DEFAULT_PAGINATION_CLASS': 'core.pagination.Paginacion',
    'PAGE_SIZE': 20,
    'DEFAULT_THROTTLE_RATES': {'login': '10/minute'},
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
}


# Licencias: se consultan al backend admin con un token interno.

ADMIN_SAAS_API_URL = os.environ.get('ADMIN_SAAS_API_URL', '').rstrip('/')
INTERNAL_API_TOKEN = os.environ.get('INTERNAL_API_TOKEN', '')
LICENSE_FALLBACK = os.environ.get('LICENSE_FALLBACK', 'local').lower()
LICENSE_CACHE_SECONDS = int(os.environ.get('LICENSE_CACHE_SECONDS', '300'))


# Integraciones externas

INTEGRATIONS_MOCK = env_bool('INTEGRATIONS_MOCK', 'true')

WHATSAPP_TOKEN = os.environ.get('WHATSAPP_TOKEN', '')
WHATSAPP_PHONE_NUMBER_ID = os.environ.get('WHATSAPP_PHONE_NUMBER_ID', '')
WHATSAPP_VERIFY_TOKEN = os.environ.get('WHATSAPP_VERIFY_TOKEN', '')
WHATSAPP_APP_SECRET = os.environ.get('WHATSAPP_APP_SECRET', '')
WHATSAPP_API_VERSION = os.environ.get('WHATSAPP_API_VERSION', 'v21.0')

OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')

GOOGLE_MAPS_API_KEY = os.environ.get('GOOGLE_MAPS_API_KEY', '')

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'loggers': {
        'delismart': {'handlers': ['console'], 'level': 'INFO'},
    },
}
