from django.contrib import admin

from .models import Device, Interface, IPv4Route, NextHop, PollingSchedule, TaskLog


@admin.register(TaskLog)
class TaskLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "job_id", "device", "level", "message")
    list_filter = ("level", "device")
    search_fields = ("job_id", "message", "device__hostname")
    readonly_fields = ("job_id", "device", "level", "message", "created_at")


class PollingScheduleInline(admin.TabularInline):
    model = PollingSchedule
    extra = 0
    fields = ("task_type", "interval_minutes", "enabled", "last_run_at", "next_run_at")
    readonly_fields = ("last_run_at", "next_run_at")


class InterfaceInline(admin.TabularInline):
    model = Interface
    extra = 0
    fields = ("name", "oper_status", "collected_at")
    readonly_fields = ("collected_at",)


class IPv4RouteInline(admin.TabularInline):
    model = IPv4Route
    extra = 0
    fields = ("prefix", "collected_at")
    readonly_fields = ("collected_at",)


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("hostname", "created_at", "updated_at")
    search_fields = ("hostname",)
    inlines = [PollingScheduleInline, InterfaceInline, IPv4RouteInline]


class NextHopInline(admin.TabularInline):
    model = NextHop
    extra = 0
    fields = ("ip_address",)


@admin.register(Interface)
class InterfaceAdmin(admin.ModelAdmin):
    list_display = ("device", "name", "oper_status", "collected_at")
    list_filter = ("oper_status", "device")
    search_fields = ("name", "device__hostname")


@admin.register(IPv4Route)
class IPv4RouteAdmin(admin.ModelAdmin):
    list_display = ("device", "prefix", "collected_at")
    list_filter = ("device",)
    search_fields = ("prefix", "device__hostname")
    inlines = [NextHopInline]


@admin.register(NextHop)
class NextHopAdmin(admin.ModelAdmin):
    list_display = ("route", "ip_address")
    search_fields = ("ip_address", "route__prefix", "route__device__hostname")


@admin.register(PollingSchedule)
class PollingScheduleAdmin(admin.ModelAdmin):
    list_display = ("device", "task_type", "interval_minutes", "enabled", "last_run_at", "next_run_at")
    list_filter = ("enabled", "task_type", "device")
    readonly_fields = ("last_run_at", "next_run_at")
