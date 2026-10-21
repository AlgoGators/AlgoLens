"""Deliver a RenderedEmail over SMTP, and build the MIME message (shared with the preview tool)."""

import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from algolens.application.reports.ports import Mailer


def build_message(sender, recipients, email):
    """multipart/alternative (text, then HTML), with the charts inline on the HTML part."""
    msg = EmailMessage()
    msg["Subject"] = email.subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain="algolens")
    msg.set_content(email.text)
    msg.add_alternative(email.html, subtype="html")
    html_part = msg.get_payload()[-1]
    for cid, data in email.images.items():
        subtype = "jpeg" if data[:3] == b"\xff\xd8\xff" else "png"
        html_part.add_related(data, maintype="image", subtype=subtype, cid=f"<{cid}>",
                              filename=f"{cid}.{'jpg' if subtype == 'jpeg' else 'png'}",
                              disposition="inline")
    return msg


class SmtpMailer(Mailer):
    """SMTP settings come from the environment; nothing is read until a send."""

    def __init__(self, env=None):
        self.env = os.environ if env is None else env

    def send(self, recipients, email):
        host = self.env.get("SMTP_HOST")
        user = self.env.get("SMTP_USER")
        password = self.env.get("SMTP_PASSWORD")
        sender = self.env.get("REPORT_FROM") or user
        if not (host and sender):
            raise RuntimeError("SMTP_HOST and REPORT_FROM (or SMTP_USER) must be set")
        port = int(self.env.get("SMTP_PORT", "587"))
        message = build_message(sender, list(recipients), email)
        context = ssl.create_default_context()
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, context=context, timeout=30)
        else:
            server = smtplib.SMTP(host, port, timeout=30)
        with server:
            if port != 465:
                server.starttls(context=context)
            if user and password:
                server.login(user, password)
            server.send_message(message)
