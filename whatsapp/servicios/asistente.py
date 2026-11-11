"""Asistente de pedidos por WhatsApp.

Modo real: OpenAI gpt-4o-mini con function calling sobre `Herramientas`.
Modo simulado: un intérprete de reglas que usa las mismas herramientas, para demostrar el flujo
completo sin OPENAI_API_KEY.

TODO(credenciales): requiere OPENAI_API_KEY. El modelo se cambia con OPENAI_MODEL.
"""

import json
import logging
import re

import requests
from django.conf import settings

from ..models import Mensaje
from .herramientas import Herramientas, normalizar
from .integraciones import simulado

logger = logging.getLogger('delismart.asistente')

OPENAI_URL = 'https://api.openai.com/v1/chat/completions'
TIMEOUT_SECONDS = 20
MAX_PASOS = 5
HISTORIAL = 20

NUMEROS = {'un': 1, 'una': 1, 'uno': 1, 'dos': 2, 'tres': 3, 'cuatro': 4, 'cinco': 5, 'seis': 6}
SALUDOS = ('hola', 'buenas', 'buenos dias', 'buenas tardes', 'buenas noches', 'hi', 'alo')


# --- Modo simulado ----------------------------------------------------------------------------

def _alias_de(plato):
    alias = [normalizar(plato.nombre), *[normalizar(a) for a in plato.alias.split(',') if a.strip()]]
    return sorted({a for a in alias if a}, key=len, reverse=True)


def interpretar_items(herramientas, texto):
    """Detecta "2 pollo entero", "una inca kola" o "1/4 de pollo" contra la carta disponible."""
    restante = f' {normalizar(texto)} '
    candidatos = [(alias, plato) for plato in herramientas.platos_disponibles() for alias in _alias_de(plato)]
    candidatos.sort(key=lambda par: len(par[0]), reverse=True)
    items = []
    for alias, plato in candidatos:
        patron = re.compile(
            r'(?:(\d+|' + '|'.join(NUMEROS) + r')\s*(?:x\s*)?(?:de\s+)?)?(?<![\w/])' + re.escape(alias) + r'(?![\w/])'
        )
        while True:
            match = patron.search(restante)
            if not match:
                break
            cantidad = match.group(1)
            cantidad = int(cantidad) if cantidad and cantidad.isdigit() else NUMEROS.get(cantidad or '', 1)
            items.append({'plato_id': plato.id, 'cantidad': cantidad})
            restante = restante[:match.start()] + ' ' + restante[match.end():]
    return items


def responder_simulado(herramientas, texto):
    t = normalizar(texto)
    respuestas = []

    if any(palabra in t for palabra in ('cancelar pedido', 'empezar de nuevo', 'borrar pedido')):
        herramientas.vaciar()
        return ['Listo, empezamos de nuevo. ' + herramientas.pedir_datos_faltantes()]

    pide_carta = any(palabra in t for palabra in ('carta', 'menu', 'precios', 'que tienen'))
    saludo = any(t.startswith(s) for s in SALUDOS)

    items = interpretar_items(herramientas, texto)
    if items:
        resultado = herramientas.agregar_items(items)
        respuestas.append('👌 Agregué: ' + ', '.join(resultado['agregados']) + '.')

    metodo = next((m for m in ('yape', 'plin', 'transferencia') if m in t), None)
    porcentaje = None
    if re.search(r'\b50\s*%?|mitad|adelanto', t):
        porcentaje = 50
    elif re.search(r'\b100\s*%?|completo|todo|total', t) and not items:
        porcentaje = 100
    if metodo or porcentaje:
        herramientas.registrar_pago(metodo, porcentaje)

    direccion = re.search(r'(?:direccion|dir|vivo en|entregar en)\s*(?:es)?\s*[:\-]?\s*(.+)', texto, re.IGNORECASE)
    if direccion is None and re.match(r'\s*(av\.?|avenida|jr\.?|jiron|calle|psje\.?|pasaje|mz\.?)\s', t):
        direccion = re.match(r'(.+)', texto)
    if direccion:
        herramientas.registrar_direccion(direccion.group(1))
        respuestas.append('🏠 Anoté tu dirección.')

    nombre = re.search(r'(?:me llamo|soy|mi nombre es)\s+([a-záéíóúñ]+(?:\s+[a-záéíóúñ]+)?)', texto, re.IGNORECASE)
    if nombre:
        herramientas.registrar_nombre(nombre.group(1).title())

    if 'resumen' in t:
        return [herramientas.resumen_pedido()]

    if pide_carta or (saludo and not herramientas.borrador['items'] and not items):
        bienvenida = herramientas.restaurante.mensaje_bienvenida or f'¡Hola! 👋 Bienvenido a {herramientas.restaurante.nombre}.'
        if saludo:
            respuestas.append(bienvenida)
        respuestas.append(herramientas.consultar_carta())

    if not respuestas and not (metodo or porcentaje):
        respuestas.append('No te entendí bien 🤔. Escribe *carta* para ver el menú o *resumen* para ver tu pedido.')

    siguiente = herramientas.pedir_datos_faltantes()
    if siguiente:
        respuestas.append(siguiente)
    return respuestas


# --- Modo OpenAI ------------------------------------------------------------------------------

TOOLS = [
    {
        'type': 'function',
        'function': {
            'name': 'consultar_carta',
            'description': 'Devuelve la carta con los platos disponibles y sus precios.',
            'parameters': {'type': 'object', 'properties': {}},
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'armar_pedido',
            'description': 'Agrega platos al pedido en curso. Usa el nombre tal como aparece en la carta.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'items': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'nombre': {'type': 'string'},
                                'cantidad': {'type': 'integer', 'minimum': 1},
                                'notas': {'type': 'string'},
                            },
                            'required': ['nombre', 'cantidad'],
                        },
                    },
                },
                'required': ['items'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'quitar_plato',
            'description': 'Quita un plato del pedido en curso.',
            'parameters': {'type': 'object', 'properties': {'nombre': {'type': 'string'}}, 'required': ['nombre']},
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'registrar_datos',
            'description': 'Guarda datos de entrega y pago que el cliente mencione.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'nombre_cliente': {'type': 'string'},
                    'direccion': {'type': 'string'},
                    'referencia': {'type': 'string'},
                    'metodo_pago': {'type': 'string', 'enum': ['yape', 'plin', 'transferencia']},
                    'porcentaje_adelanto': {'type': 'integer', 'enum': [50, 100]},
                },
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'pedir_datos_faltantes',
            'description': 'Indica qué dato falta para cerrar el pedido y el texto sugerido para pedirlo.',
            'parameters': {'type': 'object', 'properties': {}},
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'resumen_pedido',
            'description': 'Devuelve el resumen con totales, tiempo estimado e instrucciones de pago.',
            'parameters': {'type': 'object', 'properties': {}},
        },
    },
]


def _ejecutar(herramientas, nombre, argumentos):
    if nombre == 'consultar_carta':
        return herramientas.consultar_carta()
    if nombre == 'armar_pedido':
        return herramientas.agregar_items(argumentos.get('items', []))
    if nombre == 'quitar_plato':
        return herramientas.quitar_item(argumentos.get('nombre', ''))
    if nombre == 'registrar_datos':
        if argumentos.get('nombre_cliente'):
            herramientas.registrar_nombre(argumentos['nombre_cliente'])
        if argumentos.get('direccion'):
            herramientas.registrar_direccion(argumentos['direccion'], argumentos.get('referencia', ''))
        return herramientas.registrar_pago(argumentos.get('metodo_pago'), argumentos.get('porcentaje_adelanto'))
    if nombre == 'pedir_datos_faltantes':
        return {'faltan': herramientas.datos_faltantes(), 'sugerencia': herramientas.pedir_datos_faltantes()}
    if nombre == 'resumen_pedido':
        return herramientas.resumen_pedido()
    return {'error': f'Herramienta desconocida: {nombre}'}


def _prompt_sistema(herramientas):
    r = herramientas.restaurante
    return (
        f'Eres el asistente de pedidos por WhatsApp de la pollería "{r.nombre}" en Perú. '
        'Respondes en español peruano, amable y breve (máximo 4 líneas, usa emojis con moderación). '
        'Solo vendes lo que devuelve consultar_carta; nunca inventes platos ni precios. '
        'Usa armar_pedido cuando el cliente pida platos y registrar_datos para dirección y pago. '
        'Para cerrar el pedido se necesitan: platos, ubicación de WhatsApp, método de pago '
        '(Yape, Plin o transferencia), adelanto del 50% o 100% y la captura del comprobante. '
        'Usa pedir_datos_faltantes para saber qué falta y resumen_pedido antes de pedir el pago. '
        f'Radio de cobertura: {r.radio_cobertura_km} km. Tiempo de preparación: {r.tiempo_preparacion_min} min.'
    )


def _historial(conversacion):
    mensajes = list(conversacion.mensajes.exclude(texto='').order_by('-creado_en', '-id')[:HISTORIAL])
    return [
        {'role': 'user' if m.direccion == Mensaje.Direccion.ENTRANTE else 'assistant', 'content': m.texto}
        for m in reversed(mensajes)
    ]


def responder_openai(herramientas, texto):
    mensajes = [{'role': 'system', 'content': _prompt_sistema(herramientas)}, *_historial(herramientas.conversacion)]
    if not mensajes[-1:] or mensajes[-1].get('content') != texto:
        mensajes.append({'role': 'user', 'content': texto})

    for _ in range(MAX_PASOS):
        response = requests.post(
            OPENAI_URL,
            headers={'Authorization': f'Bearer {settings.OPENAI_API_KEY}'},
            json={'model': settings.OPENAI_MODEL, 'messages': mensajes, 'tools': TOOLS, 'temperature': 0.3},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        mensaje = response.json()['choices'][0]['message']
        llamadas = mensaje.get('tool_calls') or []
        if not llamadas:
            return [mensaje.get('content') or herramientas.pedir_datos_faltantes()]
        mensajes.append(mensaje)
        for llamada in llamadas:
            argumentos = json.loads(llamada['function'].get('arguments') or '{}')
            resultado = _ejecutar(herramientas, llamada['function']['name'], argumentos)
            mensajes.append({
                'role': 'tool',
                'tool_call_id': llamada['id'],
                'content': resultado if isinstance(resultado, str) else json.dumps(resultado, ensure_ascii=False),
            })
    return [herramientas.pedir_datos_faltantes()]


def responder(conversacion, texto):
    """Devuelve la lista de textos a enviar al cliente."""
    herramientas = Herramientas(conversacion)
    if simulado('openai'):
        return responder_simulado(herramientas, texto)
    try:
        return responder_openai(herramientas, texto)
    except (requests.RequestException, KeyError, ValueError) as error:
        logger.warning('OpenAI falló, responde el asistente simulado: %s', error)
        return responder_simulado(herramientas, texto)
