# users/emails.py
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

from .i18n import current_language, language_of

COMPANY_NAME = "Taurus"


def send_templated_email(subject, template, context, to, language=None):
    """
    Send emails/<template>.html with its hand-written plain-text twin emails/<template>.txt
    (stripping the HTML loses the links, e.g. the reset button).
    language: app code ("fr"); default: the language of the request being served. The templates
    use {% translate %} / {% blocktranslate %} (locale/<lang>/LC_MESSAGES/django.po).
    """
    lang = language or current_language()
    context = {"company_name": COMPANY_NAME, "support_email": settings.SUPPORT_EMAIL, "lang": lang, **context}
    with language_of(lang):
        html = render_to_string(f"emails/{template}.html", context)
        text = render_to_string(f"emails/{template}.txt", context).strip() + "\n"
    send_mail(str(subject), text, settings.DEFAULT_FROM_EMAIL, list(to), html_message=html, fail_silently=False)
