import os

from twilio.rest import Client


TWILIO_ACCOUNT_SID = os.getenv(
    "NEIGHBOURHELP_TWILIO_ACCOUNT_SID"  
)

TWILIO_AUTH_TOKEN = os.getenv(
    "NEIGHBOURHELP_TWILIO_AUTH_TOKEN"   
)

TWILIO_PHONE_NUMBER = os.getenv(
    "NEIGHBOURHELP_TWILIO_PHONE_NUMBER"
)


def send_phone_otp(recipient, otp):

    if not all([
        TWILIO_ACCOUNT_SID,
        TWILIO_AUTH_TOKEN,
        TWILIO_PHONE_NUMBER,
    ]):
        raise RuntimeError(
            "SMS verification is not configured."
        )

    client = Client(
        TWILIO_ACCOUNT_SID,
        TWILIO_AUTH_TOKEN
    )

    message = client.messages.create(
        body=(
            f"Your NeighbourHelp verification code is "
            f"{otp}. It expires in 10 minutes."
        ),
        from_=TWILIO_PHONE_NUMBER,
        to=recipient,
    )

    return message.sid