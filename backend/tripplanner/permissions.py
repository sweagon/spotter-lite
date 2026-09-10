from rest_framework.permissions import BasePermission


class IsDispatcher(BasePermission):
    """dispatchers and admins may manage the fleet; drivers can't."""

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.is_dispatcher


class IsOwnTrip(BasePermission):
    """drivers may read their own trips only; dispatchers may read all."""

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.is_dispatcher:
            return True
        return obj.driver_id == getattr(user, "driver_profile", None).id


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.is_admin