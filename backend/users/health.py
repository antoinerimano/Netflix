# users/health.py
# /api/health/: the site is up (nginx -> Django -> MySQL). Polled every 5 minutes by
# scripts/heartbeat.sh, which tells healthchecks.io. Says nothing about the data: just "ok".
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


@never_cache
@require_GET
def health_view(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:  # noqa: BLE001 (any database problem = not healthy)
        return JsonResponse({"ok": False}, status=503)
    return JsonResponse({"ok": True})
