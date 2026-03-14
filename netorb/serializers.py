from rest_framework import serializers

from .models import Interface, IPv4Route, NextHop


class InterfaceSerializer(serializers.ModelSerializer):
    device = serializers.StringRelatedField()

    class Meta:
        model = Interface
        fields = ["id", "device", "name", "oper_status", "collected_at"]


class NextHopSerializer(serializers.ModelSerializer):
    class Meta:
        model = NextHop
        fields = ["ip_address"]


class IPv4RouteSerializer(serializers.ModelSerializer):
    device = serializers.StringRelatedField()
    next_hops = NextHopSerializer(many=True, read_only=True)

    class Meta:
        model = IPv4Route
        fields = ["id", "device", "prefix", "next_hops", "collected_at"]
