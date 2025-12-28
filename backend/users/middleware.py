# users/middleware.py
from django.http import HttpResponseForbidden
from django.utils.deprecation import MiddlewareMixin

ADMIN_PREFIX = "/super-admin-7b0e/"  # keep trailing slash

# Allow these unauthenticated endpoints so you can sign in + load assets
ADMIN_ALLOWLIST = (
    f"{ADMIN_PREFIX}login/",
    f"{ADMIN_PREFIX}logout/",
    f"{ADMIN_PREFIX}password_change/",
    f"{ADMIN_PREFIX}password_reset/",
    f"{ADMIN_PREFIX}js/",             # some admin JS paths
    f"{ADMIN_PREFIX}autocomplete/",   # admin autocomplete
    "/static/",                       # admin CSS/JS/images (served here)
    "/favicon.ico",
)

class AdminBlockMiddleware(MiddlewareMixin):
    def process_request(self, request):
        path = request.path

        # Not an admin path? Let it through.
        if not path.startswith(ADMIN_PREFIX):
            return None

        user = getattr(request, "user", None)
        if user and user.is_authenticated and user.is_staff:
            # Staff is fine everywhere
            return None

        # Non-staff/anonymous: allow only the allowlist (login, logout, static, etc.)
        for allowed in ADMIN_ALLOWLIST:
            if path.startswith(allowed):
                return None

        # Everything else: block
        return HttpResponseForbidden("Forbidden")
