import logging
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

from src.config import settings

logger = logging.getLogger(__name__)


@dataclass
class EmailMessage:
    to: list[str]
    subject: str
    body_text: str = ""
    body_html: str = ""


class EmailService:
    def __init__(self):
        self.host = settings.smtp_host
        self.port = settings.smtp_port
        self.username = settings.smtp_user
        self.password = settings.smtp_password
        self.use_tls = settings.smtp_use_tls
        self.from_addr = settings.smtp_from
        self._enabled = bool(self.host and self.username)

    async def send(self, message: EmailMessage) -> bool:
        if not self._enabled:
            logger.info("Email disabled, skipping: subject=%s to=%s", message.subject, message.to)
            return False
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = self.from_addr
            msg["To"] = ", ".join(message.to)
            msg["Subject"] = message.subject
            if message.body_text:
                msg.attach(MIMEText(message.body_text, "plain"))
            if message.body_html:
                msg.attach(MIMEText(message.body_html, "html"))
            smtp = aiosmtplib.SMTP(hostname=self.host, port=self.port)
            await smtp.connect()
            if self.use_tls:
                await smtp.starttls()
            if self.username:
                await smtp.login(self.username, self.password)
            await smtp.sendmail(self.from_addr, message.to, msg.as_string())
            await smtp.quit()
            logger.info("Email sent: subject=%s to=%s", message.subject, message.to)
            return True
        except Exception as e:
            logger.error("Email send failed: %s", str(e))
            return False

    async def send_template(self, to: list[str], subject: str, template_text: str, **kwargs) -> bool:
        body = template_text.format(**kwargs)
        return await self.send(EmailMessage(to=to, subject=subject, body_text=body))


email_service = EmailService()
