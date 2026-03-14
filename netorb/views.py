import json
import time

from django.contrib.auth.decorators import login_required
from django.http import StreamingHttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET
from rest_framework import filters
from rest_framework.viewsets import ReadOnlyModelViewSet

from .models import Interface, IPv4Route, TaskLog
from .serializers import InterfaceSerializer, IPv4RouteSerializer

class InterfaceViewSet(ReadOnlyModelViewSet):
    """
    list:   GET /api/interfaces/
    retrieve: GET /api/interfaces/{id}/

    Filter by device:      ?device=sw1
    Filter by oper_status: ?oper_status=up
    Search by name:        ?search=Ethernet
    """

    serializer_class = InterfaceSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "device__hostname"]

    def get_queryset(self):
        qs = Interface.objects.select_related("device").order_by("device__hostname", "name")
        device = self.request.query_params.get("device")
        oper_status = self.request.query_params.get("oper_status")
        if device:
            qs = qs.filter(device__hostname=device)
        if oper_status:
            qs = qs.filter(oper_status=oper_status)
        return qs


class IPv4RouteViewSet(ReadOnlyModelViewSet):
    """
    list:   GET /api/routes/
    retrieve: GET /api/routes/{id}/

    Filter by device: ?device=sw1
    Search by prefix: ?search=10.0
    """

    serializer_class = IPv4RouteSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["device__hostname"]

    def get_queryset(self):
        qs = (
            IPv4Route.objects.select_related("device")
            .prefetch_related("next_hops")
            .order_by("device__hostname", "prefix")
        )
        device = self.request.query_params.get("device")
        if device:
            qs = qs.filter(device__hostname=device)
        return qs


_SSE_TIMEOUT_SECONDS = 120
_SSE_POLL_INTERVAL = 1


@login_required
def log_page(request):
    """Render the live log viewer page."""
    job_ids = (
        TaskLog.objects.order_by("-created_at")
        .values_list("job_id", flat=True)
        .distinct()[:20]
    )
    return render(request, "netorb/logs.html", {"job_ids": job_ids})


@login_required
@require_GET
def log_stream(request):
    """
    SSE endpoint — streams TaskLog rows as they are created.

    Query params:
        last_id  (int)  – stream only entries with id > last_id (default: 0)
        job_id   (str)  – filter by job; omit to stream all jobs
    """
    last_id = int(request.GET.get("last_id", 0))
    job_id = request.GET.get("job_id", "")

    def event_stream():
        nonlocal last_id
        elapsed = 0
        while elapsed < _SSE_TIMEOUT_SECONDS:
            qs = TaskLog.objects.filter(id__gt=last_id).order_by("id")
            if job_id:
                qs = qs.filter(job_id=job_id)
            for entry in qs[:100]:
                payload = json.dumps(
                    {
                        "id": entry.id,
                        "job_id": entry.job_id,
                        "device": entry.device.hostname if entry.device else None,
                        "level": entry.level,
                        "message": entry.message,
                        "created_at": entry.created_at.isoformat(),
                    }
                )
                yield f"data: {payload}\n\n"
                last_id = entry.id
            time.sleep(_SSE_POLL_INTERVAL)
            elapsed += _SSE_POLL_INTERVAL
        yield "event: close\ndata: stream timeout\n\n"

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response
