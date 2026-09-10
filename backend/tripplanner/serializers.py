from rest_framework import serializers


class TripPlanRequestSerializer(serializers.Serializer):
    current_location = serializers.CharField(max_length=300, help_text="Driver's current location")
    pickup_location = serializers.CharField(max_length=300, help_text="Pickup location")
    dropoff_location = serializers.CharField(max_length=300, help_text="Dropoff location")
    current_cycle_used = serializers.FloatField(
        min_value=0, max_value=70,
        help_text="Hours of 70-hour cycle already used in the last 8 days"
    )

    def validate_current_cycle_used(self, value):
        if value < 0 or value > 70:
            raise serializers.ValidationError("Must be between 0 and 70 hours")
        return value
