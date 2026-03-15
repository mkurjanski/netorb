import datetime as dt
import json
import pathlib
import time

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

# ---------------------------------------------------------------------------
# Diff helpers
# ---------------------------------------------------------------------------

def _parse_diff_time(value: str, default: dt.datetime) -> dt.datetime:
    """Parse a datetime-local string (YYYY-MM-DDTHH:MM) or '' / 'now' → default."""
    from django.utils import timezone as tz
    if not value or value.strip().lower() == "now":
        return default
    try:
        parsed = dt.datetime.fromisoformat(value)
        return tz.make_aware(parsed) if tz.is_naive(parsed) else parsed
    except ValueError:
        return default


def _snapshot_at(EventModel, timestamp):
    """
    Return {pgh_obj_id: event_row} for the latest state of every object
    at or before *timestamp*. Objects whose latest event is a delete are
    excluded (they did not exist at that point in time).
    """
    qs = (
        EventModel.objects
        .filter(pgh_created_at__lte=timestamp)
        .order_by("pgh_obj_id", "-pgh_created_at")
        .distinct("pgh_obj_id")
        .select_related("device")
    )
    return {e.pgh_obj_id: e for e in qs if e.pgh_label != "delete"}


def _build_diff(s1, s2, differ_fn):
    """
    Compare two snapshots and return a list of dicts with keys:
      status  – 'added' | 'removed' | 'changed'
      t1      – event row at T1 (None if added)
      t2      – event row at T2 (None if removed)
    """
    k1, k2 = set(s1), set(s2)
    rows = []
    for pk in k2 - k1:
        rows.append({"status": "added",   "t1": None,   "t2": s2[pk]})
    for pk in k1 - k2:
        rows.append({"status": "removed", "t1": s1[pk], "t2": None})
    for pk in k1 & k2:
        if differ_fn(s1[pk], s2[pk]):
            rows.append({"status": "changed", "t1": s1[pk], "t2": s2[pk]})
    return rows


def _sort_diff(rows, *key_attrs):
    order = {"changed": 0, "added": 1, "removed": 2}
    def sort_key(r):
        obj = r["t2"] or r["t1"]
        return (order[r["status"]], obj.device.ip_address) + tuple(str(getattr(obj, a)) for a in key_attrs)
    return sorted(rows, key=sort_key)


def _filter_diff_by_device(rows, ip_address):
    return [
        r for r in rows
        if (r["t1"] and r["t1"].device.ip_address == ip_address)
        or (r["t2"] and r["t2"].device.ip_address == ip_address)
    ]


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
    search_fields = ["name", "device__hostname", "device__ip_address"]

    def get_queryset(self):
        qs = Interface.objects.select_related("device").order_by("device__ip_address", "name")
        device = self.request.query_params.get("device")
        oper_status = self.request.query_params.get("oper_status")
        if device:
            qs = qs.filter(device__ip_address=device)
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
    search_fields = ["device__hostname", "device__ip_address"]

    def get_queryset(self):
        qs = IPv4Route.objects.select_related("device").order_by("device__ip_address", "prefix")
        device = self.request.query_params.get("device")
        if device:
            qs = qs.filter(device__ip_address=device)
        return qs


class InterfaceListView(ListView):
    model = Interface
    template_name = "netorb/interfaces.html"
    context_object_name = "interfaces"
    paginate_by = 100

    def get_queryset(self):
        qs = Interface.objects.select_related("device").order_by("device__ip_address", "name")
        self.f_device = self.request.GET.get("device", "")
        self.f_name = self.request.GET.get("name", "")
        self.f_status = self.request.GET.get("status", "")
        if self.f_device:
            qs = qs.filter(device__ip_address=self.f_device)
        if self.f_name:
            qs = qs.filter(name__icontains=self.f_name)
        if self.f_status:
            qs = qs.filter(oper_status=self.f_status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["devices"] = Device.objects.order_by("ip_address")
        ctx["f_device"] = self.f_device
        ctx["f_name"] = self.f_name
        ctx["f_status"] = self.f_status
        ctx["status_choices"] = Interface.OperStatus.choices
        return ctx


class RouteListView(ListView):
    model = IPv4Route
    template_name = "netorb/routes.html"
    context_object_name = "routes"
    paginate_by = 100

    def get_queryset(self):
        qs = IPv4Route.objects.select_related("device").order_by("device__ip_address", "prefix")
        self.f_device = self.request.GET.get("device", "")
        self.f_prefix = self.request.GET.get("prefix", "")
        self.f_nexthop = self.request.GET.get("nexthop", "")
        if self.f_device:
            qs = qs.filter(device__ip_address=self.f_device)
        if self.f_prefix:
            qs = qs.filter(prefix__startswith=self.f_prefix)
        if self.f_nexthop:
            qs = _filter_by_nexthop(qs, self.f_nexthop)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["devices"] = Device.objects.order_by("ip_address")
        ctx["f_device"] = self.f_device
        ctx["f_prefix"] = self.f_prefix
        ctx["f_nexthop"] = self.f_nexthop
        return ctx


_LATEST_TABS = ["interfaces", "routes", "arp", "bgp_sessions"]


def latest(request):
    tab = request.GET.get("tab", "interfaces")
    if tab not in _LATEST_TABS:
        tab = "interfaces"

    devices = Device.objects.order_by("ip_address")
    f_device = request.GET.get("device", "")
    ctx = {"tab": tab, "devices": devices, "f_device": f_device}

    if tab == "interfaces":
        qs = Interface.objects.select_related("device").order_by("device__ip_address", "name")
        f_name = request.GET.get("name", "")
        f_status = request.GET.get("status", "")
        if f_device:
            qs = qs.filter(device__ip_address=f_device)
        if f_name:
            qs = qs.filter(name__icontains=f_name)
        if f_status:
            qs = qs.filter(oper_status=f_status)
        ctx.update({"objects": qs, "f_name": f_name, "f_status": f_status,
                    "status_choices": Interface.OperStatus.choices})

    elif tab == "routes":
        qs = IPv4Route.objects.select_related("device").order_by("device__ip_address", "prefix")
        f_prefix = request.GET.get("prefix", "")
        f_nexthop = request.GET.get("nexthop", "")
        if f_device:
            qs = qs.filter(device__ip_address=f_device)
        if f_prefix:
            qs = qs.filter(prefix__startswith=f_prefix)
        if f_nexthop:
            qs = _filter_by_nexthop(qs, f_nexthop)
        ctx.update({"objects": qs, "f_prefix": f_prefix, "f_nexthop": f_nexthop})

    elif tab == "arp":
        qs = ArpEntry.objects.select_related("device").order_by("device__ip_address", "ip_address")
        f_ip = request.GET.get("ip", "")
        f_mac = request.GET.get("mac", "")
        f_interface = request.GET.get("interface", "")
        if f_device:
            qs = qs.filter(device__ip_address=f_device)
        if f_ip:
            qs = qs.filter(ip_address__startswith=f_ip)
        if f_mac:
            qs = qs.filter(mac_address__icontains=f_mac)
        if f_interface:
            qs = qs.filter(interface__icontains=f_interface)
        ctx.update({"objects": qs, "f_ip": f_ip, "f_mac": f_mac, "f_interface": f_interface})

    elif tab == "bgp_sessions":
        qs = BgpSession.objects.select_related("device").order_by("device__ip_address", "vrf", "peer_ip")
        f_vrf = request.GET.get("vrf", "")
        f_peer_ip = request.GET.get("peer_ip", "")
        f_peer_asn = request.GET.get("peer_asn", "")
        f_state = request.GET.get("state", "")
        if f_device:
            qs = qs.filter(device__ip_address=f_device)
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


class ArpEntryListView(ListView):
    model = ArpEntry
    template_name = "netorb/arp.html"
    context_object_name = "entries"
    paginate_by = 100

    def get_queryset(self):
        qs = ArpEntry.objects.select_related("device").order_by("device__ip_address", "ip_address")
        self.f_device = self.request.GET.get("device", "")
        self.f_ip = self.request.GET.get("ip", "")
        self.f_mac = self.request.GET.get("mac", "")
        self.f_interface = self.request.GET.get("interface", "")
        if self.f_device:
            qs = qs.filter(device__ip_address=self.f_device)
        if self.f_ip:
            qs = qs.filter(ip_address__startswith=self.f_ip)
        if self.f_mac:
            qs = qs.filter(mac_address__icontains=self.f_mac)
        if self.f_interface:
            qs = qs.filter(interface__icontains=self.f_interface)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["devices"] = Device.objects.order_by("ip_address")
        ctx["f_device"] = self.f_device
        ctx["f_ip"] = self.f_ip
        ctx["f_mac"] = self.f_mac
        ctx["f_interface"] = self.f_interface
        return ctx


class BgpSessionListView(ListView):
    model = BgpSession
    template_name = "netorb/bgp_sessions.html"
    context_object_name = "sessions"
    paginate_by = 100

    def get_queryset(self):
        qs = BgpSession.objects.select_related("device").order_by("device__ip_address", "vrf", "peer_ip")
        self.f_device = self.request.GET.get("device", "")
        self.f_vrf = self.request.GET.get("vrf", "")
        self.f_peer_ip = self.request.GET.get("peer_ip", "")
        self.f_peer_asn = self.request.GET.get("peer_asn", "")
        self.f_state = self.request.GET.get("state", "")
        if self.f_device:
            qs = qs.filter(device__ip_address=self.f_device)
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
        ctx["devices"] = Device.objects.order_by("ip_address")
        ctx["state_choices"] = BgpSession.PeerState.choices
        ctx["f_device"] = self.f_device
        ctx["f_vrf"] = self.f_vrf
        ctx["f_peer_ip"] = self.f_peer_ip
        ctx["f_peer_asn"] = self.f_peer_asn
        ctx["f_state"] = self.f_state
        return ctx


_HISTORY_TABS = ["interfaces", "routes", "arp", "bgp_sessions"]
_EVENT_LABELS = [("insert", "Insert"), ("update", "Update"), ("delete", "Delete")]


def history(request):
    tab = request.GET.get("tab", "interfaces")
    if tab not in _HISTORY_TABS:
        tab = "interfaces"

    devices = Device.objects.order_by("ip_address")
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
            qs = qs.filter(device__ip_address=f_device)
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
            qs = qs.filter(device__ip_address=f_device)
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
            qs = qs.filter(device__ip_address=f_device)
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
            qs = qs.filter(device__ip_address=f_device)
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


_STATUS_ORDER = {"changed": 0, "added": 1, "removed": 2}


def diff(request):
    from django.utils import timezone as tz

    tab = request.GET.get("tab", "interfaces")
    if tab not in _HISTORY_TABS:
        tab = "interfaces"

    now = tz.now()
    t1 = _parse_diff_time(request.GET.get("t1", ""), default=now - dt.timedelta(hours=24))
    t2 = _parse_diff_time(request.GET.get("t2", ""), default=now)

    fmt = lambda d: d.strftime("%Y-%m-%dT%H:%M")
    devices = Device.objects.order_by("ip_address")
    f_device = request.GET.get("device", "")

    ctx = {
        "tab": tab,
        "t1": fmt(t1),
        "t2": fmt(t2),
        "t1_raw": request.GET.get("t1", ""),
        "t2_raw": request.GET.get("t2", ""),
        "devices": devices,
        "f_device": f_device,
    }

    if tab == "interfaces":
        InterfaceEvent = apps.get_model("netorb", "InterfaceEvent")
        s1 = _snapshot_at(InterfaceEvent, t1)
        s2 = _snapshot_at(InterfaceEvent, t2)
        rows = _build_diff(s1, s2, lambda a, b: a.oper_status != b.oper_status or a.primary_ip != b.primary_ip)
        if f_device:
            rows = _filter_diff_by_device(rows, f_device)
        ctx["diff_rows"] = _sort_diff(rows, "name")

    elif tab == "routes":
        IPv4RouteEvent = apps.get_model("netorb", "IPv4RouteEvent")
        s1 = _snapshot_at(IPv4RouteEvent, t1)
        s2 = _snapshot_at(IPv4RouteEvent, t2)
        rows = _build_diff(s1, s2, lambda a, b: set(a.next_hops) != set(b.next_hops))
        if f_device:
            rows = _filter_diff_by_device(rows, f_device)
        ctx["diff_rows"] = _sort_diff(rows, "prefix")

    elif tab == "arp":
        ArpEntryEvent = apps.get_model("netorb", "ArpEntryEvent")
        s1 = _snapshot_at(ArpEntryEvent, t1)
        s2 = _snapshot_at(ArpEntryEvent, t2)
        # age excluded — it changes every poll and would create noise
        rows = _build_diff(s1, s2, lambda a, b: a.mac_address != b.mac_address or a.interface != b.interface)
        if f_device:
            rows = _filter_diff_by_device(rows, f_device)
        ctx["diff_rows"] = _sort_diff(rows, "ip_address")

    elif tab == "bgp_sessions":
        BgpSessionEvent = apps.get_model("netorb", "BgpSessionEvent")
        s1 = _snapshot_at(BgpSessionEvent, t1)
        s2 = _snapshot_at(BgpSessionEvent, t2)
        rows = _build_diff(s1, s2, lambda a, b: (
            a.peer_state != b.peer_state
            or a.peer_asn != b.peer_asn
            or a.prefixes_received != b.prefixes_received
            or a.prefixes_accepted != b.prefixes_accepted
        ))
        if f_device:
            rows = _filter_diff_by_device(rows, f_device)
        ctx["diff_rows"] = _sort_diff(rows, "vrf", "peer_ip")
        ctx["state_choices"] = BgpSession.PeerState.choices

    return render(request, "netorb/diff.html", ctx)


_SSE_TIMEOUT_SECONDS = 120
_SSE_POLL_INTERVAL = 1


def home(request):
    devices = Device.objects.annotate(
        interface_count=Count("interfaces", distinct=True),
        interfaces_up=Count("interfaces", filter=Q(interfaces__oper_status="up"), distinct=True),
        route_count=Count("ipv4_routes", distinct=True),
    ).order_by("ip_address")

    context = {
        "device_count": Device.objects.count(),
        "interface_count": Interface.objects.count(),
        "route_count": IPv4Route.objects.count(),
        "devices": devices,
    }
    return render(request, "netorb/home.html", context)


_TASK_FILES = ["services.py", "tasks.py"]
_APP_DIR = pathlib.Path(__file__).parent


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


def poll_results(request):
    qs = PollResult.objects.select_related("device").order_by("-started_at")
    selected_device = request.GET.get("device", "")
    selected_type = request.GET.get("type", "")
    if selected_device:
        qs = qs.filter(device__ip_address=selected_device)
    if selected_type:
        qs = qs.filter(check_type=selected_type)
    devices = Device.objects.order_by("ip_address")
    return render(request, "netorb/poll_results.html", {
        "results": qs[:200],
        "devices": devices,
        "selected_device": selected_device,
        "selected_type": selected_type,
    })


def log_page(request):
    """Render the live log viewer page."""
    job_ids = (
        TaskLog.objects.order_by("-created_at")
        .values_list("job_id", flat=True)
        .distinct()[:20]
    )
    return render(request, "netorb/logs.html", {"job_ids": job_ids})


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
                        "device": entry.device.display_name if entry.device else None,
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
