import json
import pathlib
import time

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import StreamingHttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET
from django.views.generic import ListView
from rest_framework import filters
from rest_framework.viewsets import ReadOnlyModelViewSet

from django.apps import apps
from django.db.models import Count, Func, Q, TextField, Value

from .models import ArpEntry, BgpSession, Device, Interface, IPv4Route, PollResult, TaskLog
from .serializers import InterfaceSerializer, IPv4RouteSerializer

def _filter_by_nexthop(qs, value):
    """Filter routes where any next hop contains *value* (case-insensitive)."""
    return qs.annotate(
        _nh_str=Func("next_hops", Value(" "), function="array_to_string", output_field=TextField())
    ).filter(_nh_str__icontains=value)

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
        qs = IPv4Route.objects.select_related("device").order_by("device__hostname", "prefix")
        device = self.request.query_params.get("device")
        if device:
            qs = qs.filter(device__hostname=device)
        return qs


class InterfaceListView(LoginRequiredMixin, ListView):
    model = Interface
    template_name = "netorb/interfaces.html"
    context_object_name = "interfaces"
    paginate_by = 100

    def get_queryset(self):
        qs = Interface.objects.select_related("device").order_by("device__hostname", "name")
        self.f_device = self.request.GET.get("device", "")
        self.f_name = self.request.GET.get("name", "")
        self.f_status = self.request.GET.get("status", "")
        if self.f_device:
            qs = qs.filter(device__hostname=self.f_device)
        if self.f_name:
            qs = qs.filter(name__icontains=self.f_name)
        if self.f_status:
            qs = qs.filter(oper_status=self.f_status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["devices"] = Device.objects.values_list("hostname", flat=True).order_by("hostname")
        ctx["f_device"] = self.f_device
        ctx["f_name"] = self.f_name
        ctx["f_status"] = self.f_status
        ctx["status_choices"] = Interface.OperStatus.choices
        return ctx


class RouteListView(LoginRequiredMixin, ListView):
    model = IPv4Route
    template_name = "netorb/routes.html"
    context_object_name = "routes"
    paginate_by = 100

    def get_queryset(self):
        qs = IPv4Route.objects.select_related("device").order_by("device__hostname", "prefix")
        self.f_device = self.request.GET.get("device", "")
        self.f_prefix = self.request.GET.get("prefix", "")
        self.f_nexthop = self.request.GET.get("nexthop", "")
        if self.f_device:
            qs = qs.filter(device__hostname=self.f_device)
        if self.f_prefix:
            qs = qs.filter(prefix__startswith=self.f_prefix)
        if self.f_nexthop:
            qs = _filter_by_nexthop(qs, self.f_nexthop)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["devices"] = Device.objects.values_list("hostname", flat=True).order_by("hostname")
        ctx["f_device"] = self.f_device
        ctx["f_prefix"] = self.f_prefix
        ctx["f_nexthop"] = self.f_nexthop
        return ctx


_LATEST_TABS = ["interfaces", "routes", "arp", "bgp_sessions"]


@login_required
def latest(request):
    tab = request.GET.get("tab", "interfaces")
    if tab not in _LATEST_TABS:
        tab = "interfaces"

    devices = Device.objects.values_list("hostname", flat=True).order_by("hostname")
    f_device = request.GET.get("device", "")
    ctx = {"tab": tab, "devices": devices, "f_device": f_device}

    if tab == "interfaces":
        qs = Interface.objects.select_related("device").order_by("device__hostname", "name")
        f_name = request.GET.get("name", "")
        f_status = request.GET.get("status", "")
        if f_device:
            qs = qs.filter(device__hostname=f_device)
        if f_name:
            qs = qs.filter(name__icontains=f_name)
        if f_status:
            qs = qs.filter(oper_status=f_status)
        ctx.update({"objects": qs, "f_name": f_name, "f_status": f_status,
                    "status_choices": Interface.OperStatus.choices})

    elif tab == "routes":
        qs = IPv4Route.objects.select_related("device").order_by("device__hostname", "prefix")
        f_prefix = request.GET.get("prefix", "")
        f_nexthop = request.GET.get("nexthop", "")
        if f_device:
            qs = qs.filter(device__hostname=f_device)
        if f_prefix:
            qs = qs.filter(prefix__startswith=f_prefix)
        if f_nexthop:
            qs = _filter_by_nexthop(qs, f_nexthop)
        ctx.update({"objects": qs, "f_prefix": f_prefix, "f_nexthop": f_nexthop})

    elif tab == "arp":
        qs = ArpEntry.objects.select_related("device").order_by("device__hostname", "ip_address")
        f_ip = request.GET.get("ip", "")
        f_mac = request.GET.get("mac", "")
        f_interface = request.GET.get("interface", "")
        if f_device:
            qs = qs.filter(device__hostname=f_device)
        if f_ip:
            qs = qs.filter(ip_address__startswith=f_ip)
        if f_mac:
            qs = qs.filter(mac_address__icontains=f_mac)
        if f_interface:
            qs = qs.filter(interface__icontains=f_interface)
        ctx.update({"objects": qs, "f_ip": f_ip, "f_mac": f_mac, "f_interface": f_interface})

    elif tab == "bgp_sessions":
        qs = BgpSession.objects.select_related("device").order_by("device__hostname", "vrf", "peer_ip")
        f_vrf = request.GET.get("vrf", "")
        f_peer_ip = request.GET.get("peer_ip", "")
        f_peer_asn = request.GET.get("peer_asn", "")
        f_state = request.GET.get("state", "")
        if f_device:
            qs = qs.filter(device__hostname=f_device)
        if f_vrf:
            qs = qs.filter(vrf__icontains=f_vrf)
        if f_peer_ip:
            qs = qs.filter(peer_ip__startswith=f_peer_ip)
        if f_peer_asn:
            qs = qs.filter(peer_asn=f_peer_asn)
        if f_state:
            qs = qs.filter(peer_state=f_state)
        ctx.update({"objects": qs, "f_vrf": f_vrf, "f_peer_ip": f_peer_ip,
                    "f_peer_asn": f_peer_asn, "f_state": f_state,
                    "state_choices": BgpSession.PeerState.choices})

    return render(request, "netorb/latest.html", ctx)


class ArpEntryListView(LoginRequiredMixin, ListView):
    model = ArpEntry
    template_name = "netorb/arp.html"
    context_object_name = "entries"
    paginate_by = 100

    def get_queryset(self):
        qs = ArpEntry.objects.select_related("device").order_by("device__hostname", "ip_address")
        self.f_device = self.request.GET.get("device", "")
        self.f_ip = self.request.GET.get("ip", "")
        self.f_mac = self.request.GET.get("mac", "")
        self.f_interface = self.request.GET.get("interface", "")
        if self.f_device:
            qs = qs.filter(device__hostname=self.f_device)
        if self.f_ip:
            qs = qs.filter(ip_address__startswith=self.f_ip)
        if self.f_mac:
            qs = qs.filter(mac_address__icontains=self.f_mac)
        if self.f_interface:
            qs = qs.filter(interface__icontains=self.f_interface)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["devices"] = Device.objects.values_list("hostname", flat=True).order_by("hostname")
        ctx["f_device"] = self.f_device
        ctx["f_ip"] = self.f_ip
        ctx["f_mac"] = self.f_mac
        ctx["f_interface"] = self.f_interface
        return ctx


class BgpSessionListView(LoginRequiredMixin, ListView):
    model = BgpSession
    template_name = "netorb/bgp_sessions.html"
    context_object_name = "sessions"
    paginate_by = 100

    def get_queryset(self):
        qs = BgpSession.objects.select_related("device").order_by("device__hostname", "vrf", "peer_ip")
        self.f_device = self.request.GET.get("device", "")
        self.f_vrf = self.request.GET.get("vrf", "")
        self.f_peer_ip = self.request.GET.get("peer_ip", "")
        self.f_peer_asn = self.request.GET.get("peer_asn", "")
        self.f_state = self.request.GET.get("state", "")
        if self.f_device:
            qs = qs.filter(device__hostname=self.f_device)
        if self.f_vrf:
            qs = qs.filter(vrf__icontains=self.f_vrf)
        if self.f_peer_ip:
            qs = qs.filter(peer_ip__startswith=self.f_peer_ip)
        if self.f_peer_asn:
            qs = qs.filter(peer_asn=self.f_peer_asn)
        if self.f_state:
            qs = qs.filter(peer_state=self.f_state)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["devices"] = Device.objects.values_list("hostname", flat=True).order_by("hostname")
        ctx["state_choices"] = BgpSession.PeerState.choices
        ctx["f_device"] = self.f_device
        ctx["f_vrf"] = self.f_vrf
        ctx["f_peer_ip"] = self.f_peer_ip
        ctx["f_peer_asn"] = self.f_peer_asn
        ctx["f_state"] = self.f_state
        return ctx


_HISTORY_TABS = ["interfaces", "routes", "arp", "bgp_sessions"]
_EVENT_LABELS = [("insert", "Insert"), ("update", "Update"), ("delete", "Delete")]


@login_required
def history(request):
    tab = request.GET.get("tab", "interfaces")
    if tab not in _HISTORY_TABS:
        tab = "interfaces"

    devices = Device.objects.values_list("hostname", flat=True).order_by("hostname")
    f_device = request.GET.get("device", "")
    f_event = request.GET.get("event", "")
    ctx = {
        "tab": tab,
        "devices": devices,
        "f_device": f_device,
        "f_event": f_event,
        "event_labels": _EVENT_LABELS,
    }

    if tab == "interfaces":
        InterfaceEvent = apps.get_model("netorb", "InterfaceEvent")
        qs = InterfaceEvent.objects.select_related("device").order_by("-pgh_created_at")
        f_name = request.GET.get("name", "")
        f_status = request.GET.get("status", "")
        if f_device:
            qs = qs.filter(device__hostname=f_device)
        if f_event:
            qs = qs.filter(pgh_label=f_event)
        if f_name:
            qs = qs.filter(name__icontains=f_name)
        if f_status:
            qs = qs.filter(oper_status=f_status)
        ctx.update({
            "objects": qs[:500],
            "f_name": f_name,
            "f_status": f_status,
            "status_choices": Interface.OperStatus.choices,
        })

    elif tab == "routes":
        IPv4RouteEvent = apps.get_model("netorb", "IPv4RouteEvent")
        qs = IPv4RouteEvent.objects.select_related("device").order_by("-pgh_created_at")
        f_prefix = request.GET.get("prefix", "")
        if f_device:
            qs = qs.filter(device__hostname=f_device)
        if f_event:
            qs = qs.filter(pgh_label=f_event)
        if f_prefix:
            qs = qs.filter(prefix__startswith=f_prefix)
        ctx.update({"objects": qs[:500], "f_prefix": f_prefix})

    elif tab == "arp":
        ArpEntryEvent = apps.get_model("netorb", "ArpEntryEvent")
        qs = ArpEntryEvent.objects.select_related("device").order_by("-pgh_created_at")
        f_ip = request.GET.get("ip", "")
        f_mac = request.GET.get("mac", "")
        if f_device:
            qs = qs.filter(device__hostname=f_device)
        if f_event:
            qs = qs.filter(pgh_label=f_event)
        if f_ip:
            qs = qs.filter(ip_address__startswith=f_ip)
        if f_mac:
            qs = qs.filter(mac_address__icontains=f_mac)
        ctx.update({"objects": qs[:500], "f_ip": f_ip, "f_mac": f_mac})

    elif tab == "bgp_sessions":
        BgpSessionEvent = apps.get_model("netorb", "BgpSessionEvent")
        qs = BgpSessionEvent.objects.select_related("device").order_by("-pgh_created_at")
        f_peer_ip = request.GET.get("peer_ip", "")
        f_state = request.GET.get("state", "")
        if f_device:
            qs = qs.filter(device__hostname=f_device)
        if f_event:
            qs = qs.filter(pgh_label=f_event)
        if f_peer_ip:
            qs = qs.filter(peer_ip__startswith=f_peer_ip)
        if f_state:
            qs = qs.filter(peer_state=f_state)
        ctx.update({
            "objects": qs[:500],
            "f_peer_ip": f_peer_ip,
            "f_state": f_state,
            "state_choices": BgpSession.PeerState.choices,
        })

    return render(request, "netorb/history.html", ctx)


_SSE_TIMEOUT_SECONDS = 120
_SSE_POLL_INTERVAL = 1


@login_required
def home(request):
    devices = Device.objects.annotate(
        interface_count=Count("interfaces", distinct=True),
        interfaces_up=Count("interfaces", filter=Q(interfaces__oper_status="up"), distinct=True),
        route_count=Count("ipv4_routes", distinct=True),
    ).order_by("hostname")

    context = {
        "device_count": Device.objects.count(),
        "interface_count": Interface.objects.count(),
        "route_count": IPv4Route.objects.count(),
        "devices": devices,
    }
    return render(request, "netorb/home.html", context)


_TASK_FILES = ["services.py", "tasks.py"]
_APP_DIR = pathlib.Path(__file__).parent


@login_required
def tasks(request):
    active_file = request.GET.get("file", _TASK_FILES[0])
    if active_file not in _TASK_FILES:
        active_file = _TASK_FILES[0]
    source = (_APP_DIR / active_file).read_text()
    return render(request, "netorb/tasks.html", {
        "files": [{"name": f} for f in _TASK_FILES],
        "active_file": active_file,
        "lines": source.splitlines(),
    })


@login_required
def poll_results(request):
    qs = PollResult.objects.select_related("device").order_by("-started_at")
    selected_device = request.GET.get("device", "")
    selected_type = request.GET.get("type", "")
    if selected_device:
        qs = qs.filter(device__hostname=selected_device)
    if selected_type:
        qs = qs.filter(check_type=selected_type)
    devices = Device.objects.values_list("hostname", flat=True).order_by("hostname")
    return render(request, "netorb/poll_results.html", {
        "results": qs[:200],
        "devices": devices,
        "selected_device": selected_device,
        "selected_type": selected_type,
    })


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
