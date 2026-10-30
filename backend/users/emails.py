# users/emails.py
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

COMPANY_NAME = "Taurus"


def send_templated_email(subject, template, context, to):
    """
    Send emails/<template>.html with its hand-written plain-text twin emails/<template>.txt
    (stripping the HTML loses the links, e.g. the reset button).
    """
    context = {"company_name": COMPANY_NAME, "support_email": settings.SUPPORT_EMAIL, **context}
    html = render_to_string(f"emails/{template}.html", context)
    text = render_to_string(f"emails/{template}.txt", context).strip() + "\n"
    send_mail(subject, text, settings.DEFAULT_FROM_EMAIL, list(to), html_message=html, fail_silently=False)
