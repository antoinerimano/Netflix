from rest_framework.throttling import SimpleRateThrottle


class _IPRateThrottle(SimpleRateThrottle):
    """Throttle by client IP, whether or not the request is authenticated."""
    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class AuthRateThrottle(_IPRateThrottle):
    scope = "auth"


class PasswordResetRateThrottle(_IPRateThrottle):
    scope = "password_reset"
