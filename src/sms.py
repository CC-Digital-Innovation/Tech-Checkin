from abc import ABC, abstractmethod

from twilio.rest import Client


class SMSBaseController(ABC):
    @abstractmethod
    def send_text(self, to: str, message: str):
        pass


class TwilioController(SMSBaseController):
    def __init__(self, username: str, password: str, from_: str, admin_num: str | None = None):
        self.client = Client(username, password)
        self.from_ = from_
        self.admin_num = admin_num

    def send_text(self, to: str, message: str):
        msg_instance = self.client.messages.create(
            body=message,
            from_=self.from_,
            to=to
        )
        return msg_instance
