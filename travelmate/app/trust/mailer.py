"""Password-reset emails over SMTP (free with e.g. a Gmail app password); optional.

Configure TRAVELMATE_SMTP_HOST, TRAVELMATE_SMTP_PORT (587, STARTTLS), TRAVELMATE_SMTP_USER,
TRAVELMATE_SMTP_PASSWORD and TRAVELMATE_SMTP_FROM. Without a host the API logs the link instead.
The password is never logged; send failures are logged by type only.
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage

logger = logging.getLogger(__name__)


class Mailer:
    def __init__(self, host="", port=587, user="", password="", sender="", smtp=smtplib.SMTP):
        self.host, self.port, self.user, self.password = host, port, user, password
        self.sender = sender or user
        self.smtp = smtp

    @property
    def enabled(self):
        return bool(self.host and self.sender)

    def send_reset(self, to, name, link):
        message = EmailMessage()
        message["Subject"] = "TravelMate — đặt lại mật khẩu"
        message["From"] = self.sender
        message["To"] = to
        message.set_content(
            f"Chào {name},\n\nBạn (hoặc ai đó) vừa yêu cầu đặt lại mật khẩu TravelMate. Mở link sau trong 30 phút:\n\n"
            f"{link}\n\nNếu không phải bạn, hãy bỏ qua email này; mật khẩu hiện tại vẫn giữ nguyên.\n\nTravelMate"
        )
        with self.smtp(self.host, self.port, timeout=15) as client:
            client.starttls(context=ssl.create_default_context())
            if self.user:
                client.login(self.user, self.password)
            client.send_message(message)
