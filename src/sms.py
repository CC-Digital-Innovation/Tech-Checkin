import time
from abc import ABC, abstractmethod

import requests
from twilio.rest import Client


class SMSBaseController(ABC):
    def __init__(self, admin_num: str | None = None):
        self.admin_num = admin_num

    @abstractmethod
    def send_text(self, to: str, message: str):
        pass


class TwilioController(SMSBaseController):
    def __init__(self, username: str, password: str, account_sid: str, from_: str, admin_num: str | None = None):
        self.client = Client(username, password, account_sid)
        self.from_ = from_
        super().__init__(admin_num)

    def send_text(self, to: str, message: str):
        msg_instance = self.client.messages.create(
            body=message,
            from_=self.from_,
            to=to
        )
        return msg_instance


class TextbeltController(SMSBaseController):
    base_url = 'https://textbelt.com/text'

    def __init__(self, key: str, sender: str | None = None, admin_num: str | None = None):
        self.key = key
        self.sender = sender
        super().__init__(admin_num)

    def send_text(self, to: str, message: str):
        data = {
            'sender': self.sender,
            'phone': to,
            'message': message,
            'key': self.key
        }
        resp = requests.post(self.base_url, data)
        resp.raise_for_status()
        resp_json = resp.json()
        if not resp_json['success']:
            raise RuntimeError(resp_json['error'])
        time.sleep(0.5)  # introduce slight delay due to rate limits (note does not stop separate threads/processes)
        return resp_json
