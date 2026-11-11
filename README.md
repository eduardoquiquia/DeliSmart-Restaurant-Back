# DeliSmart Restaurant Backend

API de Django REST Framework para el panel de cada pollería y su canal de pedidos por WhatsApp con IA. Usa únicamente PostgreSQL en Neon: sin `DATABASE_URL` el proyecto no arranca.

## Puesta en marcha

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
cp .env.example .env          # completa DATABASE_URL
.venv/Scripts/python manage.py migrate
.venv/Scripts/python manage.py seed_demo
.venv/Scripts/python manage.py runserver 8001
```

`seed_demo` crea la pollería **El Sabrosito** (`elsabrosito`) con carta, insumos, clientes, dos semanas de pedidos y un pedido de WhatsApp con comprobante esperando validación. Personal demo, todos con la contraseña `demo12345` (se cambia con `--password`):

| Usuario | Rol |
| --- | --- |
| `admin` | Administrador: todo, incluidos usuarios y configuración |
| `cajero` | Pedidos, clientes, conversaciones, simulador y reportes |
| `cocina` | Tablero de pedidos, carta (disponibilidad) e inventario |

`seed_demo --reset` borra y recrea la pollería demo.

Las pruebas corren en una base temporal `test_*` del mismo servidor PostgreSQL:

```bash
.venv/Scripts/python manage.py test
```

## Multi-tenant

Base y esquema compartidos. Cada tabla operativa tiene una FK `restaurante` y todas las vistas filtran por el restaurante del usuario autenticado (`core/tenancy.py`). Las FKs que llegan en una petición solo aceptan objetos del mismo restaurante. `Restaurante.subdominio` es la llave compartida con `tenants.Tenant` de `delismart-admin-saas-back`.

## Licencias

Antes de responder cualquier endpoint del panel (`core.permissions.LicenciaVigente`) y antes de procesar un mensaje de WhatsApp, se comprueba que la licencia esté `activa` y sin vencer. Si falla, el panel responde `402` y el mensaje se ignora. `auth/me/` siempre responde, para mostrar el motivo del bloqueo.

- Con `ADMIN_SAAS_API_URL` e `INTERNAL_API_TOKEN`, se consulta al backend admin y la respuesta se guarda `LICENSE_CACHE_SECONDS`.
- Si el admin no responde, `LICENSE_FALLBACK=local` usa la última licencia guardada; `deny` bloquea.
- Sin `ADMIN_SAAS_API_URL` manda la licencia local del restaurante (la que pone `seed_demo` o el admin de Django).

## Flujo de pedidos por WhatsApp

```
Meta webhook ─┐
              ├─> pipeline: licencia → cliente y chat → asistente IA (carta, armar pedido,
Simulador ────┘   datos faltantes, resumen) → ubicación y cobertura → comprobante
                  → Pedido "pendiente_validacion" → el cajero confirma el pago
                  → en_preparacion → en_camino → entregado (o cancelado)
```

Cada cambio de estado de un pedido de WhatsApp avisa al cliente en el mismo chat. Si el personal escribe en una conversación, el asistente se pausa en ese chat.

## Integraciones

| Servicio | Variables | Código |
| --- | --- | --- |
| Meta WhatsApp Cloud API | `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET` | `whatsapp/servicios/cliente_whatsapp.py`, `whatsapp/views.py` |
| OpenAI (`gpt-4o-mini`) | `OPENAI_API_KEY`, `OPENAI_MODEL` | `whatsapp/servicios/asistente.py`, `herramientas.py` |
| Google Maps Routes API | `GOOGLE_MAPS_API_KEY` | `whatsapp/servicios/rutas.py` |

**Modo simulado.** `INTEGRATIONS_MOCK=true` (por defecto) simula todo: los mensajes no salen a Meta, el asistente usa reglas en vez de OpenAI y la distancia se estima en línea recta × 1.3 a 25 km/h. Con `false`, cada servicio se activa solo si tiene sus claves. `GET /api/v1/integraciones/` muestra qué está simulado y qué claves faltan.

### Pendiente de credenciales (`TODO(credenciales)` en el código)

- [ ] Meta: app de negocio con WhatsApp, número verificado, token permanente de usuario del sistema y permisos `whatsapp_business_messaging` y `whatsapp_business_management` aprobados.
- [ ] Registrar el webhook `https://<dominio>/api/whatsapp/webhook/` con `WHATSAPP_VERIFY_TOKEN` y suscribir el campo `messages`. Meta exige HTTPS público.
- [ ] Guardar en cada restaurante su `whatsapp_phone_number_id`: así el webhook sabe a qué pollería va cada mensaje.
- [ ] `OPENAI_API_KEY` con saldo.
- [ ] `GOOGLE_MAPS_API_KEY` con la Routes API habilitada.
- [ ] `delismart-admin-saas-back` todavía no expone `GET /api/internal/licencias/<subdominio>/` (con `Authorization: Bearer <INTERNAL_API_TOKEN>`, responde `estado`, `plan` y `fecha_vencimiento`). Hasta entonces deja `ADMIN_SAAS_API_URL` vacío.
- [ ] Producción: procesar el webhook en una cola (Celery/RQ) para responder a Meta en menos de 5 s, y guardar los medios en un almacenamiento externo.

## API

Todo cuelga de `/api/v1/` y exige un JWT del personal con licencia vigente, salvo `health/` y `auth/login/`.

| Ruta | Uso |
| --- | --- |
| `auth/login/`, `auth/refresh/`, `auth/me/` | Sesión, rol y estado de la licencia |
| `restaurante/` | Configuración: ubicación, cobertura, tiempos, pagos, WhatsApp |
| `categorias/`, `platos/` | Carta |
| `clientes/` | Clientes con total de pedidos y gasto |
| `insumos/`, `insumos/alertas/`, `insumos/<id>/movimientos/` | Inventario |
| `usuarios/` | Personal (solo admin) |
| `pedidos/` | Lista, detalle y alta manual. `estado`, `origen`, `desde`, `hasta`, `hoy`, `search` |
| `pedidos/nuevos/` | Polling del cajero: pedidos de WhatsApp por validar |
| `pedidos/tablero/` | Pedidos activos por estado |
| `pedidos/<id>/confirmar-pago/`, `estado/`, `comprobante/` | Acciones |
| `conversaciones/`, `<id>/mensajes/`, `<id>/responder/`, `<id>/estado/` | Chats de WhatsApp |
| `simulador/` | `POST` un mensaje falso (texto, imagen o ubicación), `GET` el chat, `DELETE` reinicia |
| `reportes/resumen/` | Ventas, pedidos por estado y origen, serie diaria y productos top |
| `integraciones/` | Estado real o simulado de cada integración |

El webhook público de Meta es `/api/whatsapp/webhook/` (`GET` verificación, `POST` mensajes con `X-Hub-Signature-256`).
