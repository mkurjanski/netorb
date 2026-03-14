from django.urls import path

from . import views

urlpatterns = [
    path("logs/", views.log_page, name="log-page"),
    path("logs/stream/", views.log_stream, name="log-stream"),
]
