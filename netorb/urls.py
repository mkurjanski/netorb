from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("interfaces", views.InterfaceViewSet, basename="interface")
router.register("routes", views.IPv4RouteViewSet, basename="route")

urlpatterns = [
    path("", views.home, name="home"),
    path("logs/", views.log_page, name="log-page"),
    path("tasks/", views.tasks, name="tasks"),
    path("poll-results/", views.poll_results, name="poll-results"),
    path("logs/stream/", views.log_stream, name="log-stream"),
    path("api/", include(router.urls)),
]
