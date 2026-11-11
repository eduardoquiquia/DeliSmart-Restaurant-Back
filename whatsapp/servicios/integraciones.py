"""Qué integraciones corren de verdad y cuáles están simuladas.

INTEGRATIONS_MOCK=true simula todo. Si es false, cada servicio se activa solo cuando tiene sus
claves; si faltan, ese servicio sigue simulado y el panel lo muestra.
"""

from django.conf import settings

CLAVES = {
    'whatsapp': ('WHATSAPP_TOKEN', 'WHATSAPP_PHONE_NUMBER_ID', 'WHATSAPP_VERIFY_TOKEN', 'WHATSAPP_APP_SECRET'),
    'openai': ('OPENAI_API_KEY',),
    'google_maps': ('GOOGLE_MAPS_API_KEY',),
}


def claves_faltantes(servicio):
    return [name for name in CLAVES[servicio] if not getattr(settings, name, '')]


def simulado(servicio):
    return settings.INTEGRATIONS_MOCK or bool(claves_faltantes(servicio))


def estado():
    return {
        'modo_global_simulado': settings.INTEGRATIONS_MOCK,
        'servicios': {
            servicio: {'simulado': simulado(servicio), 'claves_faltantes': claves_faltantes(servicio)}
            for servicio in CLAVES
        },
    }
