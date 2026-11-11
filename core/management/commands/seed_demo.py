"""Crea una pollería demo con carta, personal, clientes, inventario, pedidos y un chat de WhatsApp."""

import io
import random
from datetime import timedelta
from decimal import Decimal

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageDraw

from carta.models import Categoria, Plato
from clientes.models import Cliente
from core.models import Restaurante, Usuario
from inventario.models import Insumo
from pedidos.models import HistorialEstado, Pedido
from pedidos.servicios import crear_pedido
from whatsapp.models import Conversacion, Mensaje

SUBDOMINIO = 'elsabrosito'

CARTA = {
    'Pollos a la brasa': [
        ('1/4 de pollo a la brasa', '18.90', 'Con papas fritas y ensalada.', '1/4 de pollo,cuarto de pollo,1/4'),
        ('1/2 pollo a la brasa', '34.90', 'Con papas fritas, ensalada y cremas.', '1/2 pollo,medio pollo,1/2'),
        ('Pollo a la brasa entero', '62.90', 'Con papas familiares, ensalada y cremas.', 'pollo entero,pollo a la brasa'),
    ],
    'Combos': [
        ('Combo familiar', '79.90', 'Pollo entero, papas, ensalada y gaseosa 1.5L.', 'familiar'),
        ('Combo pareja', '45.90', '1/2 pollo, papas, ensalada y 2 chichas.', 'pareja'),
    ],
    'Parrillas': [
        ('Anticuchos', '24.90', 'Dos palitos con papa dorada y choclo.', 'anticucho'),
        ('Mollejitas a la parrilla', '22.90', 'Con papas y ensalada.', 'mollejas,mollejitas'),
    ],
    'Bebidas': [
        ('Inca Kola 1.5L', '9.50', '', 'inca kola,inka kola,gaseosa'),
        ('Chicha morada 1L', '10.00', 'Hecha en casa.', 'chicha'),
        ('Agua sin gas 625ml', '3.50', '', 'agua'),
    ],
    'Extras': [
        ('Porción de papas', '8.00', '', 'papas'),
        ('Ensalada clásica', '7.50', '', 'ensalada'),
    ],
}

INSUMOS = [
    ('Pollo entero', 'unidad', 18, 20, '14.50', 'Avícola San Fernando'),
    ('Papa amarilla', 'kg', 42, 25, '3.20', 'Mercado Mayorista'),
    ('Aceite vegetal', 'l', 6, 10, '8.90', 'Distribuidora Lima'),
    ('Carbón', 'kg', 60, 30, '2.50', 'Carbonera Norte'),
    ('Inca Kola 1.5L', 'unidad', 48, 24, '5.80', 'Lindley'),
    ('Lechuga', 'unidad', 9, 12, '1.50', 'Mercado Mayorista'),
    ('Ají amarillo', 'kg', 4, 2, '6.00', 'Mercado Mayorista'),
]

CLIENTES = [
    ('María Quispe', '51987654321', 'Av. Larco 345, Miraflores', -12.1225, -77.0301),
    ('José Ramírez', '51976543210', 'Calle Alcanfores 120, Miraflores', -12.1268, -77.0272),
    ('Lucía Fernández', '51965432109', 'Av. Arequipa 4520, Miraflores', -12.1140, -77.0345),
    ('Carlos Huamán', '51954321098', 'Jr. Domingo Elías 210, Miraflores', -12.1302, -77.0225),
    ('Ana Torres', '51943210987', 'Av. Benavides 1180, Miraflores', -12.1258, -77.0210),
    ('Pedro Castillo', '51932109876', 'Calle Berlín 455, Miraflores', -12.1192, -77.0338),
]

PERSONAL = [
    ('admin', 'Rosa', 'Mendoza', Usuario.Rol.ADMIN),
    ('cajero', 'Luis', 'Paredes', Usuario.Rol.CAJERO),
    ('cocina', 'Jorge', 'Salazar', Usuario.Rol.COCINA),
]


def imagen_comprobante(monto):
    imagen = Image.new('RGB', (360, 640), '#742284')
    dibujo = ImageDraw.Draw(imagen)
    dibujo.rectangle((24, 120, 336, 520), fill='white')
    dibujo.text((120, 60), 'yape (demo)', fill='white')
    dibujo.text((60, 170), '¡Yapeaste!', fill='#742284')
    dibujo.text((60, 230), f'S/ {monto:.2f}', fill='black')
    dibujo.text((60, 290), 'Pollería El Sabrosito', fill='black')
    dibujo.text((60, 330), timezone.localtime().strftime('%d %b %Y %H:%M'), fill='gray')
    dibujo.text((60, 470), 'Comprobante simulado', fill='gray')
    buffer = io.BytesIO()
    imagen.save(buffer, 'PNG')
    return ContentFile(buffer.getvalue(), name='comprobante-demo.png')


class Command(BaseCommand):
    help = 'Crea la pollería demo "El Sabrosito" con datos de prueba.'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true', help='Borra y vuelve a crear la pollería demo.')
        parser.add_argument('--password', default='demo12345', help='Contraseña del personal demo.')

    @transaction.atomic
    def handle(self, *args, **options):
        existente = Restaurante.objects.filter(subdominio=SUBDOMINIO).first()
        if existente and not options['reset']:
            self.stdout.write(self.style.WARNING('La pollería demo ya existe. Usa --reset para recrearla.'))
            return
        if existente:
            # Pedidos y platos protegen a clientes y categorías: se borran antes que el restaurante.
            Pedido.objects.filter(restaurante=existente).delete()
            Plato.objects.filter(restaurante=existente).delete()
            existente.delete()

        random.seed(7)
        hoy = timezone.localdate()
        restaurante = Restaurante.objects.create(
            nombre='Pollería El Sabrosito',
            subdominio=SUBDOMINIO,
            ruc='20601234567',
            telefono='014455667',
            direccion='Av. José Pardo 610, Miraflores, Lima',
            latitud=Decimal('-12.119400'),
            longitud=Decimal('-77.033500'),
            radio_cobertura_km=Decimal('5.00'),
            tiempo_preparacion_min=25,
            costo_delivery=Decimal('5.00'),
            yape_numero='987111222',
            yape_titular='Rosa Mendoza',
            plin_numero='987111222',
            plin_titular='Rosa Mendoza',
            transferencia_banco='BCP',
            transferencia_cuenta='193-4567890-0-12',
            transferencia_cci='00219300456789001214',
            transferencia_titular='El Sabrosito S.A.C.',
            whatsapp_numero='51987111222',
            mensaje_bienvenida='¡Hola! 👋 Bienvenido a Pollería El Sabrosito, el mejor pollo a la brasa de Miraflores.',
            licencia_estado=Restaurante.EstadoLicencia.ACTIVA,
            licencia_plan='pro',
            licencia_vencimiento=hoy + timedelta(days=30),
        )

        for username, nombre, apellido, rol in PERSONAL:
            Usuario.objects.filter(username=username).delete()
            user = Usuario(
                username=username, first_name=nombre, last_name=apellido, rol=rol,
                email=f'{username}@elsabrosito.pe', restaurante=restaurante,
            )
            user.set_password(options['password'])
            user.save()

        platos = []
        for orden, (categoria_nombre, items) in enumerate(CARTA.items()):
            categoria = Categoria.objects.create(restaurante=restaurante, nombre=categoria_nombre, orden=orden)
            for nombre, precio, descripcion, alias in items:
                platos.append(Plato.objects.create(
                    restaurante=restaurante, categoria=categoria, nombre=nombre, precio=Decimal(precio),
                    descripcion=descripcion, alias=alias,
                ))
        Plato.objects.filter(restaurante=restaurante, nombre='Mollejitas a la parrilla').update(disponible=False)

        for nombre, unidad, stock, minimo, costo, proveedor in INSUMOS:
            Insumo.objects.create(
                restaurante=restaurante, nombre=nombre, unidad=unidad, stock=stock, stock_minimo=minimo,
                costo_unitario=Decimal(costo), proveedor=proveedor,
            )

        clientes = [
            Cliente.objects.create(
                restaurante=restaurante, nombre=nombre, telefono=telefono, direccion=direccion,
                latitud=Decimal(str(lat)), longitud=Decimal(str(lng)),
            )
            for nombre, telefono, direccion, lat, lng in CLIENTES
        ]

        self._historial(restaurante, platos, clientes)
        self._chat_whatsapp(restaurante, platos, clientes[0])

        self.stdout.write(self.style.SUCCESS(
            f'Pollería demo lista. Personal: admin, cajero y cocina (contraseña: {options["password"]}).'
        ))

    def _historial(self, restaurante, platos, clientes):
        disponibles = [p for p in platos if p.disponible]
        ahora = timezone.now()
        for dias_atras in range(13, -1, -1):
            for _ in range(random.randint(2, 6)):
                cliente = random.choice(clientes)
                items = [
                    {'plato': plato, 'cantidad': random.randint(1, 2)}
                    for plato in random.sample(disponibles, random.randint(1, 3))
                ]
                origen = random.choice([Pedido.Origen.WHATSAPP, Pedido.Origen.WHATSAPP, Pedido.Origen.MANUAL])
                pedido = crear_pedido(
                    restaurante=restaurante, cliente=cliente, items=items, origen=origen,
                    metodo_pago=random.choice(['yape', 'plin', 'transferencia']) if origen == 'whatsapp' else 'efectivo',
                    porcentaje_adelanto=random.choice([50, 100]) if origen == 'whatsapp' else 0,
                    direccion_entrega=cliente.direccion, latitud=cliente.latitud, longitud=cliente.longitud,
                    distancia_km=Decimal(str(round(random.uniform(0.6, 4.5), 2))),
                    tiempo_traslado_min=random.randint(5, 18),
                )
                if dias_atras == 0:
                    estado = random.choice([Pedido.Estado.EN_PREPARACION, Pedido.Estado.EN_CAMINO, Pedido.Estado.ENTREGADO])
                else:
                    estado = random.choices([Pedido.Estado.ENTREGADO, Pedido.Estado.CANCELADO], weights=[9, 1])[0]
                creado = ahora - timedelta(days=dias_atras, hours=random.randint(0, 6), minutes=random.randint(0, 59))
                Pedido.objects.filter(pk=pedido.pk).update(
                    estado=estado, creado_en=creado, actualizado_en=creado + timedelta(minutes=40),
                    pago_confirmado=estado != Pedido.Estado.CANCELADO,
                )
                HistorialEstado.objects.filter(pedido=pedido).update(creado_en=creado)
                if estado != Pedido.Estado.PENDIENTE_VALIDACION:
                    HistorialEstado.objects.create(pedido=pedido, estado=estado)

    def _chat_whatsapp(self, restaurante, platos, cliente):
        """Un pedido de WhatsApp recién llegado, con su chat y comprobante, para validar en caja."""
        conversacion = Conversacion.objects.create(
            restaurante=restaurante, cliente=cliente, telefono=cliente.telefono,
            ultimo_mensaje_en=timezone.now(), no_leidos=2,
        )
        entero = next(p for p in platos if p.nombre == 'Pollo a la brasa entero')
        gaseosa = next(p for p in platos if p.nombre == 'Inca Kola 1.5L')
        chat = [
            ('entrante', 'cliente', 'Hola, buenas noches'),
            ('saliente', 'asistente', restaurante.mensaje_bienvenida + ' Escribe *carta* para ver el menú.'),
            ('entrante', 'cliente', 'Quiero 1 pollo entero y 1 inca kola'),
            ('saliente', 'asistente', '👌 Agregué: 1 x Pollo a la brasa entero, 1 x Inca Kola 1.5L.\n📍 Envíanos tu ubicación.'),
            ('entrante', 'cliente', ''),
            ('saliente', 'asistente', '📍 ¡Ubicación recibida! Estás a 0.5 km, unos 2 min en moto.\n💳 ¿Cómo vas a pagar?'),
            ('entrante', 'cliente', 'Por yape, el 100%'),
        ]
        for direccion, autor, texto in chat:
            Mensaje.objects.create(
                conversacion=conversacion, direccion=direccion, autor=autor,
                tipo='ubicacion' if direccion == 'entrante' and not texto else 'texto',
                texto=texto or cliente.direccion,
                latitud=cliente.latitud if not texto else None, longitud=cliente.longitud if not texto else None,
            )
        pedido = crear_pedido(
            restaurante=restaurante, cliente=cliente, conversacion=conversacion, origen=Pedido.Origen.WHATSAPP,
            items=[{'plato': entero, 'cantidad': 1}, {'plato': gaseosa, 'cantidad': 1}],
            metodo_pago='yape', porcentaje_adelanto=100, direccion_entrega=cliente.direccion,
            latitud=cliente.latitud, longitud=cliente.longitud, distancia_km=Decimal('0.52'), tiempo_traslado_min=2,
        )
        contenido = imagen_comprobante(pedido.monto_adelanto).read()
        mensaje = Mensaje.objects.create(conversacion=conversacion, direccion='entrante', autor='cliente', tipo='imagen')
        mensaje.imagen.save('comprobante-demo.png', ContentFile(contenido), save=True)
        pedido.comprobante.save('comprobante-demo.png', ContentFile(contenido), save=True)
        Mensaje.objects.create(
            conversacion=conversacion, direccion='saliente', autor='asistente',
            texto=f'🙌 ¡Recibimos tu comprobante! Tu pedido *#{pedido.numero}* quedó registrado y estamos validando tu pago.',
        )
