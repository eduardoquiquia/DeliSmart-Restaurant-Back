"""Herramientas del asistente: operan sobre el borrador de pedido guardado en la conversación.

Las usa tanto el modelo de OpenAI (function calling) como el asistente simulado, para que el
resultado en el panel sea el mismo en ambos modos.
"""

import re
import unicodedata
from decimal import Decimal

from carta.models import Plato
from pedidos.models import Pedido

from . import rutas

METODOS = {
    Pedido.MetodoPago.YAPE: 'Yape',
    Pedido.MetodoPago.PLIN: 'Plin',
    Pedido.MetodoPago.TRANSFERENCIA: 'Transferencia',
}


def normalizar(texto):
    texto = unicodedata.normalize('NFKD', texto or '').encode('ascii', 'ignore').decode().lower()
    return re.sub(r'\s+', ' ', texto).strip()


def soles(valor):
    return f'S/ {Decimal(valor):.2f}'


class Herramientas:
    def __init__(self, conversacion):
        self.conversacion = conversacion
        self.restaurante = conversacion.restaurante
        borrador = conversacion.borrador or {}
        borrador.setdefault('items', [])
        self.borrador = borrador

    def guardar(self):
        self.conversacion.borrador = self.borrador
        self.conversacion.save(update_fields=['borrador'])

    def platos_disponibles(self):
        return Plato.objects.filter(
            restaurante=self.restaurante, disponible=True, categoria__activa=True
        ).select_related('categoria')

    # --- Carta -------------------------------------------------------------------------------

    def consultar_carta(self):
        lineas = [f'📋 *Carta de {self.restaurante.nombre}*']
        categoria = None
        for plato in self.platos_disponibles().order_by('categoria__orden', 'categoria__nombre', 'precio'):
            if plato.categoria.nombre != categoria:
                categoria = plato.categoria.nombre
                lineas.append(f'\n*{categoria}*')
            lineas.append(f'• {plato.nombre} — {soles(plato.precio)}')
        if len(lineas) == 1:
            return 'Por ahora no tenemos platos disponibles. 🙏'
        return '\n'.join(lineas)

    def buscar_plato(self, referencia):
        if isinstance(referencia, int) or str(referencia).isdigit():
            return self.platos_disponibles().filter(pk=int(referencia)).first()
        objetivo = normalizar(str(referencia))
        mejor = None
        for plato in self.platos_disponibles():
            nombres = [normalizar(plato.nombre), *[normalizar(a) for a in plato.alias.split(',') if a.strip()]]
            if objetivo in nombres:
                return plato
            if any(objetivo in nombre or nombre in objetivo for nombre in nombres):
                mejor = mejor or plato
        return mejor

    # --- Armar pedido ------------------------------------------------------------------------

    def agregar_items(self, items):
        agregados, no_encontrados = [], []
        for item in items:
            plato = self.buscar_plato(item.get('plato_id') or item.get('nombre', ''))
            if plato is None:
                no_encontrados.append(str(item.get('nombre') or item.get('plato_id')))
                continue
            cantidad = max(1, int(item.get('cantidad') or 1))
            existente = next((i for i in self.borrador['items'] if i['plato_id'] == plato.id), None)
            if existente:
                existente['cantidad'] += cantidad
            else:
                self.borrador['items'].append({
                    'plato_id': plato.id,
                    'nombre': plato.nombre,
                    'precio': str(plato.precio),
                    'cantidad': cantidad,
                    'notas': item.get('notas', ''),
                })
            agregados.append(f'{cantidad} x {plato.nombre}')
        self.guardar()
        return {'agregados': agregados, 'no_encontrados': no_encontrados}

    def quitar_item(self, nombre):
        plato = self.buscar_plato(nombre)
        antes = len(self.borrador['items'])
        if plato:
            self.borrador['items'] = [i for i in self.borrador['items'] if i['plato_id'] != plato.id]
        self.guardar()
        return {'quitado': len(self.borrador['items']) < antes}

    def vaciar(self):
        self.borrador = {'items': []}
        self.guardar()

    def registrar_direccion(self, direccion, referencia=''):
        self.borrador['direccion'] = direccion.strip()[:255]
        if referencia:
            self.borrador['referencia'] = referencia.strip()[:255]
        self.guardar()
        return {'direccion': self.borrador['direccion']}

    def registrar_ubicacion(self, latitud, longitud, direccion=''):
        ruta = rutas.ruta_desde_restaurante(self.restaurante, latitud, longitud)
        self.borrador.update({
            'latitud': float(latitud),
            'longitud': float(longitud),
            'distancia_km': float(ruta.distancia_km) if ruta else None,
            'tiempo_traslado_min': ruta.tiempo_min if ruta else None,
            'fuera_de_cobertura': not rutas.dentro_de_cobertura(self.restaurante, ruta),
        })
        if direccion:
            self.borrador['direccion'] = direccion[:255]
        self.guardar()
        return {
            'distancia_km': self.borrador['distancia_km'],
            'tiempo_traslado_min': self.borrador['tiempo_traslado_min'],
            'dentro_de_cobertura': not self.borrador['fuera_de_cobertura'],
            'radio_cobertura_km': float(self.restaurante.radio_cobertura_km),
        }

    def registrar_pago(self, metodo=None, porcentaje=None):
        if metodo in METODOS:
            self.borrador['metodo_pago'] = metodo
        if porcentaje in (50, 100, '50', '100'):
            self.borrador['porcentaje_adelanto'] = int(porcentaje)
        self.guardar()
        return {'metodo_pago': self.borrador.get('metodo_pago'), 'porcentaje_adelanto': self.borrador.get('porcentaje_adelanto')}

    def registrar_nombre(self, nombre):
        cliente = self.conversacion.cliente
        if nombre and not cliente.nombre:
            cliente.nombre = nombre.strip()[:120]
            cliente.save(update_fields=['nombre', 'actualizado_en'])

    # --- Estado del borrador -----------------------------------------------------------------

    def totales(self):
        subtotal = sum((Decimal(i['precio']) * i['cantidad'] for i in self.borrador['items']), Decimal('0'))
        total = subtotal + self.restaurante.costo_delivery
        porcentaje = self.borrador.get('porcentaje_adelanto') or 100
        return subtotal, total, (total * porcentaje / 100).quantize(Decimal('0.01'))

    def datos_faltantes(self):
        faltan = []
        if not self.borrador['items']:
            faltan.append('platos')
        if self.borrador.get('latitud') is None:
            faltan.append('ubicacion')
        if not self.borrador.get('metodo_pago'):
            faltan.append('metodo_pago')
        if not self.borrador.get('porcentaje_adelanto'):
            faltan.append('porcentaje_adelanto')
        if not self.borrador.get('comprobante_mensaje_id'):
            faltan.append('comprobante')
        return faltan

    def pedir_datos_faltantes(self):
        if self.borrador.get('fuera_de_cobertura'):
            return (
                f'😔 Tu ubicación está a {self.borrador["distancia_km"]:.1f} km y solo llegamos hasta '
                f'{self.restaurante.radio_cobertura_km} km. Si quieres, envíanos otra ubicación.'
            )
        faltan = self.datos_faltantes()
        if not faltan:
            return ''
        siguiente = faltan[0]
        if siguiente == 'platos':
            return '¿Qué te gustaría pedir? Escribe por ejemplo: "2 pollo a la brasa entero y 1 inca kola 1.5L". Escribe *carta* para ver el menú.'
        if siguiente == 'ubicacion':
            return '📍 Envíanos tu *ubicación* (clip ➜ Ubicación) y la dirección con alguna referencia para calcular el delivery.'
        if siguiente == 'metodo_pago':
            return '💳 ¿Cómo vas a pagar? *Yape*, *Plin* o *transferencia*.'
        if siguiente == 'porcentaje_adelanto':
            return '¿Pagarás el *100%* ahora o un adelanto del *50%* (el resto al recibir)?'
        return self.resumen_pedido() + '\n\n📸 Cuando pagues, envíanos la *captura del comprobante* por aquí.'

    def instrucciones_pago(self):
        metodo = self.borrador.get('metodo_pago')
        r = self.restaurante
        if metodo == Pedido.MetodoPago.YAPE and r.yape_numero:
            return f'Yapea al *{r.yape_numero}* ({r.yape_titular or r.nombre}).'
        if metodo == Pedido.MetodoPago.PLIN and r.plin_numero:
            return f'Plinea al *{r.plin_numero}* ({r.plin_titular or r.nombre}).'
        if metodo == Pedido.MetodoPago.TRANSFERENCIA and r.transferencia_cuenta:
            cci = f' · CCI {r.transferencia_cci}' if r.transferencia_cci else ''
            return f'Transfiere a {r.transferencia_banco} cta. *{r.transferencia_cuenta}*{cci} ({r.transferencia_titular or r.nombre}).'
        return ''

    def resumen_pedido(self):
        if not self.borrador['items']:
            return 'Aún no tienes platos en tu pedido.'
        subtotal, total, adelanto = self.totales()
        lineas = ['🧾 *Resumen de tu pedido*']
        for item in self.borrador['items']:
            lineas.append(f'• {item["cantidad"]} x {item["nombre"]} — {soles(Decimal(item["precio"]) * item["cantidad"])}')
        lineas.append(f'Subtotal: {soles(subtotal)}')
        if self.restaurante.costo_delivery:
            lineas.append(f'Delivery: {soles(self.restaurante.costo_delivery)}')
        lineas.append(f'*Total: {soles(total)}*')
        if self.borrador.get('tiempo_traslado_min') is not None:
            minutos = self.restaurante.tiempo_preparacion_min + self.borrador['tiempo_traslado_min']
            lineas.append(f'🕒 Tiempo estimado: {minutos} min ({self.borrador["distancia_km"]:.1f} km)')
        if self.borrador.get('porcentaje_adelanto'):
            lineas.append(f'A pagar ahora ({self.borrador["porcentaje_adelanto"]}%): *{soles(adelanto)}*')
        instrucciones = self.instrucciones_pago()
        if instrucciones:
            lineas.append(instrucciones)
        return '\n'.join(lineas)
