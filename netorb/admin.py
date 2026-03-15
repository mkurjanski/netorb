from django.contrib import admin, messages

from .models import ArpEntry, BgpSession, Device, Interface, IPv4Route, LldpNeighbor, PollResult, PollingTask, TaskLog
from .tasks import run_polling_task


@admin.register(TaskLog)
class TaskLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "job_id", "device", "level", "message")
    list_filter = ("level", "device")
    search_fields = ("job_id", "message", "device__hostname", "device__ip_address")
    readonly_fields = ("job_id", "device", "level", "message", "created_at")


class InterfaceInline(admin.TabularInline):
    model = Interface
    extra = 0
    fields = ("name", "oper_status", "primary_ip", "collected_at")
    readonly_fields = ("collected_at",)


class IPv4RouteInline(admin.TabularInline):
    model = IPv4Route
    extra = 0
    fields = ("prefix", "collected_at")
    readonly_fields = ("collected_at",)


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("ip_address", "hostname", "description", "created_at", "updated_at")
    search_fields = ("ip_address", "hostname")
    inlines = [InterfaceInline, IPv4RouteInline]


@admin.register(Interface)
class InterfaceAdmin(admin.ModelAdmin):
    list_display = ("device", "name", "oper_status", "primary_ip", "collected_at")
    list_filter = ("oper_status", "device")
    search_fields = ("name", "primary_ip", "device__hostname", "device__ip_address")


@admin.register(IPv4Route)
class IPv4RouteAdmin(admin.ModelAdmin):
    list_display = ("device", "prefix", "collected_at")
    list_filter = ("device",)
    search_fields = ("prefix", "device__hostname", "device__ip_address")


@admin.register(ArpEntry)
class ArpEntryAdmin(admin.ModelAdmin):
    list_display = ("device", "ip_address", "mac_address", "interface", "age", "collected_at")
    list_filter = ("device", "interface")
    search_fields = ("ip_address", "mac_address", "device__hostname", "device__ip_address")
    readonly_fields = ("device", "ip_address", "mac_address", "interface", "age", "collected_at")


@admin.register(BgpSession)
class BgpSessionAdmin(admin.ModelAdmin):
    list_display = ("device", "vrf", "peer_ip", "peer_asn", "peer_state", "prefixes_received", "prefixes_accepted", "collected_at")
    list_filter = ("peer_state", "device", "vrf")
    search_fields = ("peer_ip", "device__hostname", "device__ip_address")
    readonly_fields = ("device", "vrf", "peer_ip", "peer_asn", "peer_state", "prefixes_received", "prefixes_accepted", "updown_time", "collected_at")


@admin.register(LldpNeighbor)
class LldpNeighborAdmin(admin.ModelAdmin):
    list_display = ("device", "local_port", "neighbor_device", "neighbor_port", "collected_at")
    list_filter = ("device",)
    search_fields = ("local_port", "neighbor_device", "neighbor_port", "device__hostname", "device__ip_address")
    readonly_fields = ("device", "local_port", "neighbor_device", "neighbor_port", "collected_at")


@admin.register(PollResult)
class PollResultAdmin(admin.ModelAdmin):
    list_display = ("started_at", "check_type", "duration_ms", "success", "job_id")
    list_filter = ("success", "check_type")
    search_fields = ("job_id",)
    readonly_fields = ("job_id", "check_type", "started_at", "duration_ms", "success")


@admin.register(PollingTask)
class PollingTaskAdmin(admin.ModelAdmin):
    list_display = ("name", "task_type", "last_run_at", "last_success")
    list_filter = ("task_type", "last_success")
    readonly_fields = ("last_run_at", "last_success")
    actions = ["run_now"]

    @admin.action(description="Run selected tasks now")
    def run_now(self, request, queryset):
        for task in queryset:
            run_polling_task(task)
        self.message_user(request, f"Ran {queryset.count()} task(s).", messages.SUCCESS)
