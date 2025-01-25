from abc import ABC, abstractmethod

from loguru import logger
from twilio.rest import Client


class SMSBaseController(ABC):
    @abstractmethod
    def send_text(self, to: str, message: str):
        pass


class TwilioController(SMSBaseController):
    def __init__(self, account_sid: str, auth_token: str, from_: str, admin_num: str | None = None):
        self.client = Client(account_sid, auth_token)
        self.from_ = from_
        self.admin_num = admin_num

    def send_text(self, to: str, message: str):
        message = self.client.messages.create(
            body=message,
            from_=self.from_,
            to=to
        )
        logger.debug(message.body)
