from loguru import logger


def send_text(contact: str, message: str):
    # TODO Call twilio function to send text
    logger.info(f'Sending {message} to {contact}')
