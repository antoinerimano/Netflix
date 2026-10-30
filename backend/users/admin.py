from django import forms
from django.contrib import admin, messages
from django.utils.html import format_html, format_html_join

from .models import Provider
from .providers import (
    PLACEHOLDER_RE, PLACEHOLDERS, PROBE_EPISODE, PROBE_MOVIE,
    build_url, check_providers, normalize_domain,
)


class ProviderForm(forms.ModelForm):
    class Meta:
        model = Provider
        fields = "__all__"
        widgets = {"backup_domains": forms.Textarea(attrs={"rows": 3})}

    def clean_domain(self):
        domain = normalize_domain(self.cleaned_data["domain"])
        if not domain:
            raise forms.ValidationError("Enter a domain like vidfast.pro or https://vidfast.pro")
        return domain

    def clean_backup_domains(self):
        lines = [l for l in self.cleaned_data["backup_domains"].splitlines() if l.strip()]
        domains = [normalize_domain(l) for l in lines]
        bad = [l for l, d in zip(lines, domains) if not d]
        if bad:
            raise forms.ValidationError(f"Invalid domain(s): {', '.join(bad)}")
        return "\n".join(domains)

    def _clean_path(self, name):
        path = self.cleaned_data[name].strip()
        if path and not path.startswith("/"):
            raise forms.ValidationError("Must start with / (the domain is added in front).")
        unknown = set(PLACEHOLDER_RE.findall(path)) - PLACEHOLDERS
        if unknown:
            raise forms.ValidationError(
                f"Unknown placeholder(s) {sorted(unknown)}. Allowed: {sorted(PLACEHOLDERS)}"
            )
        return path

    def clean_movie_path(self):
        return self._clean_path("movie_path")

    def clean_episode_path(self):
        return self._clean_path("episode_path")


@admin.register(Provider)
class ProviderAdmin(admin.ModelAdmin):
    form = ProviderForm
    list_display = ("label", "domain", "status_badge", "checked_at", "suggested_domain", "enabled", "priority", "auto_switch")
    list_display_links = ("label",)
    list_editable = ("domain", "enabled", "priority", "auto_switch")
    actions = ["check_now", "accept_suggested_domain"]
    readonly_fields = ("status", "status_detail", "checked_at", "suggested_domain", "domain_changed_at", "example_links")
    fieldsets = (
        (None, {"fields": ("key", "label", "enabled", "priority")}),
        ("Domain", {"fields": ("domain", "backup_domains", "auto_switch")}),
        ("Link templates", {
            "fields": ("movie_path", "episode_path", "example_links"),
            "description": "Placeholders: {tmdb_id} {imdb_id} {season} {episode}. "
                           "Link = domain + path. Leave a path empty if the provider has no movies / no TV.",
        }),
        ("Health check", {"fields": ("status", "status_detail", "checked_at", "suggested_domain", "domain_changed_at")}),
    )

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        color = {"up": "#2e7d32", "down": "#c62828"}.get(obj.status, "#777")
        return format_html('<b style="color:{}" title="{}">{}</b>', color, obj.status_detail, obj.get_status_display())

    @admin.display(description="Example links")
    def example_links(self, obj):
        if not obj.pk:
            return "Save first."
        links = [
            ("Movie (Fight Club)", build_url(obj.domain, obj.movie_path, **PROBE_MOVIE)),
            ("Episode (Breaking Bad S1E1)", build_url(obj.domain, obj.episode_path, **PROBE_EPISODE)),
        ]
        return format_html_join(
            "", '<div>{}: <a href="{}" target="_blank" rel="noopener">{}</a></div>',
            ((label, url, url) for label, url in links if url),
        ) or "-"

    @admin.action(description="Check selected providers now")
    def check_now(self, request, queryset):
        for line in check_providers(queryset):
            self.message_user(request, line, messages.SUCCESS if ": up" in line else messages.WARNING)

    @admin.action(description="Use the suggested domain")
    def accept_suggested_domain(self, request, queryset):
        from .providers import _switch_domain
        changed = 0
        for p in queryset.exclude(suggested_domain=""):
            _switch_domain(p, p.suggested_domain, "accepted in admin")
            p.save()
            changed += 1
        self.message_user(request, f"{changed} provider(s) switched to their suggested domain.")
