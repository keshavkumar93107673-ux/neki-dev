
import os
import smtplib
from email.message import EmailMessage
import streamlit as st


# =========================================================
# EMAIL CONFIGURATION
# =========================================================

SMTP_SERVER = "smtp-relay.brevo.com"
SMTP_PORT = 587

SMTP_LOGIN = "bc3904001@smtp-brevo.com"
EMAIL_ADDRESS = "sumansanjay406@gmail.com"


def _get_setting(name, default=""):
    value = os.getenv(name)

    if value:
        return value

    try:
        value = st.secrets.get(name, default)
        return value or default
    except Exception:
        return default


# Supports both the existing deployed secret and the new name.
SMTP_PASSWORD = (
    _get_setting("SMTP_PASSWORD")
    or _get_setting("BREVO_SMTP_KEY")
)


# Use the deployed URL by default; override locally if needed.
BASE_URL = (
    _get_setting("NEKI_BASE_URL")
    or _get_setting(
        "BASE_URL",
        "https://neki-community.streamlit.app"
    )
).rstrip("/")


def _send_email(message):
    if not SMTP_PASSWORD:
        raise RuntimeError(
            "SMTP credential is missing. Configure "
            "SMTP_PASSWORD or BREVO_SMTP_KEY in Streamlit Secrets."
        )

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_LOGIN, SMTP_PASSWORD)
        server.send_message(message)


# =========================================================
# SEND VERIFICATION EMAIL
# =========================================================

def send_verification_email(recipient, token):
    verification_link = f"{BASE_URL}/?verify={token}"

    message = EmailMessage()
    message["Subject"] = "Verify your Neki account"
    message["From"] = EMAIL_ADDRESS
    message["To"] = recipient

    message.set_content(f"""
Hello,

Thank you for registering with Neki.

Please verify your email address by clicking the link below:

{verification_link}

This verification link will expire in 24 hours.

If you did not create this account, you can safely ignore this email.

Neki Team
""")

    _send_email(message)


# =========================================================
# SEND PASSWORD RESET EMAIL
# =========================================================

def send_password_reset_email(recipient, token):
    reset_link = f"{BASE_URL}/?reset={token}"

    message = EmailMessage()
    message["Subject"] = "Reset your Neki password"
    message["From"] = EMAIL_ADDRESS
    message["To"] = recipient

    message.set_content(f"""
Hello,

We received a request to reset your Neki password.

Use the link below to choose a new password:

{reset_link}

This link expires in one hour and can only be used once.

If you did not request a password reset, you can safely
ignore this email. Your existing password will remain unchanged.

Neki Team
""")

    _send_email(message)
