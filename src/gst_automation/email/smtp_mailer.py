from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

from gst_automation.core.exceptions import ConfigurationError
from gst_automation.core.settings import Settings
from gst_automation.vault.base import SecretRef
from gst_automation.vault.factory import build_vault


@dataclass(frozen=True, slots=True)
class SmtpMailer:
    settings: Settings

    async def send_with_attachment(
        self,
        *,
        to_email: str,
        cc_email: str | None,
        subject: str,
        body: str,
        attachment_path: Path,
        filename: str,
    ) -> None:
        if not self.settings.smtp_host or not self.settings.smtp_user or not self.settings.smtp_from:
            raise ConfigurationError("SMTP_HOST/SMTP_USER/SMTP_FROM must be configured")
        if not self.settings.smtp_password_secret:
            raise ConfigurationError("SMTP_PASSWORD_SECRET must be configured (vault secret id)")
        ns, key = self.settings.smtp_password_secret.split(":", 1)
        pw = await build_vault(self.settings).get_secret(SecretRef(namespace=ns, key=key))

        msg = EmailMessage()
        msg["From"] = self.settings.smtp_from
        msg["To"] = to_email
        if cc_email:
            msg["Cc"] = cc_email
        msg["Subject"] = subject
        msg.set_content(body)

        data = attachment_path.read_bytes()
        msg.add_attachment(
            data,
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=filename,
        )

        context = ssl.create_default_context()
        with smtplib.SMTP(self.settings.smtp_host, int(self.settings.smtp_port)) as s:
            s.starttls(context=context)
            s.login(self.settings.smtp_user, pw)
            s.send_message(msg)

