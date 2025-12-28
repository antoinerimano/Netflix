from rest_framework import serializers
from users.models import Title

class ImpressionItemSerializer(serializers.Serializer):
    profile_id = serializers.IntegerField()
    title_id = serializers.IntegerField()
    session_id = serializers.CharField()
    row_type = serializers.CharField(required=False, allow_blank=True)
    position = serializers.IntegerField(required=False, default=0)
    device = serializers.CharField(required=False, allow_blank=True, default="")
    country = serializers.CharField(required=False, allow_blank=True, default="")

class ImpressionInSerializer(serializers.Serializer):
    items = ImpressionItemSerializer(many=True)


class ActionInSerializer(serializers.Serializer):
    profile_id = serializers.IntegerField()
    title_id = serializers.IntegerField()
    action = serializers.ChoiceField(choices=[
        "click", "outbound", "like", "dislike", "add_to_list", "not_interested", "search_click"
    ])
    session_id = serializers.CharField()
    provider = serializers.CharField(required=False, allow_blank=True, default="")


