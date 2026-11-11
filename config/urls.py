from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from whatsapp.views import WebhookView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/whatsapp/webhook/', WebhookView.as_view()),
    path('api/v1/', include('config.api_urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
