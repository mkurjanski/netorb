from rest_framework import serializers

from .models import Interface, IPv4Route


class InterfaceSerializer(serializers.ModelSerializer):
    device = serializers.StringRelatedField()

    class Meta:
        model = Interface
        fields = ["id", "device", "name", "oper_status", "primary_ip", "collected_at"]


class IPv4RouteSerializer(serializers.ModelSerializer):
    device = serializers.StringRelatedField()
    next_hops = serializers.ListField(child=serializers.IPAddressField())

    class Meta:
        model = IPv4Route
        fields = ["id", "device", "prefix", "next_hops", "collected_at"]
