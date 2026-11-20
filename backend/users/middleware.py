# users/middleware.py
from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden
from django.utils.deprecation import MiddlewareMixin

ADMIN_PREFIX = "/" + settings.ADMINADMIN_URL.strip("/") + "/"  # same path as in urls.py

# Allow these unauthenticated endpoints so you can sign in + load assets
ADMIN_ALLOWLIST = (
    f"{ADMIN_PREFIX}login/",
    f"{ADMIN_PREFIX}logout/",
    f"{ADMIN_PREFIX}password_change/",
    f"{ADMIN_PREFIX}password_reset/",
    f"{ADMIN_PREFIX}js/",             # some admin JS paths
    f"{ADMIN_PREFIX}autocomplete/",   # admin autocomplete
    "/" + settings.STATIC_URL.strip("/") + "/",  # admin CSS/JS/images
    "/favicon.ico",
)

class AdminBlockMiddleware(MiddlewareMixin):
    """The Django admin is for staff only: everyone else gets its sign-in page, nothing more."""

    def process_request(self, request):
        path = request.path

        # Not an admin path? Let it through.
        if not path.startswith(ADMIN_PREFIX):
            return None

        user = getattr(request, "user", None)
        if user and user.is_authenticated and user.is_staff:
            # Staff is fine everywhere
            return None

        # Non-staff/anonymous: allow only the allowlist (login, logout, static, etc.), with or
        # without the final slash ("/login" used to be Forbidden instead of the sign-in page)
        slashed = path if path.endswith("/") else path + "/"
        for allowed in ADMIN_ALLOWLIST:
            if slashed.startswith(allowed):
                return None

        # not signed in: the admin's sign-in page, then back here
        if not (user and user.is_authenticated):
            return redirect_to_login(request.get_full_path(), f"{ADMIN_PREFIX}login/")

        # signed in but not staff
        return HttpResponseForbidden("Forbidden")
