"""
Brevo (formerly Sendinblue) API Email Backend for Django.
Uses HTTP API instead of SMTP - works on Render where SMTP is blocked.

Setup:
1. Go to app.brevo.com -> Account -> SMTP & API -> API Keys
2. Create a new API key
3. Add to Render environment variables:
   BREVO_API_KEY=your-api-key-here
   EMAIL_BACKEND=core.brevo_backend.BrevoEmailBackend
   DEFAULT_FROM_EMAIL=kemimonday00@gmail.com
4. pip install sib-api-v3-sdk  (add to requirements.txt)
   OR use requests library (no extra install needed)
"""

import json
import urllib.request
import urllib.error
from django.core.mail.backends.base import BaseEmailBackend
from django.conf import settings


class BrevoEmailBackend(BaseEmailBackend):
    """
    Django email backend using Brevo API.
    Completely bypasses SMTP - uses HTTPS requests instead.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_key = getattr(settings, 'BREVO_API_KEY', '')
        self.api_url = 'https://api.brevo.com/v3/smtp/email'

    def open(self):
        pass

    def close(self):
        pass

    def send_messages(self, email_messages):
        if not self.api_key:
            if not self.fail_silently:
                raise ValueError(
                    'BREVO_API_KEY is not set in settings. '
                    'Get your API key from app.brevo.com -> Account -> SMTP & API -> API Keys'
                )
            return 0

        sent_count = 0
        for message in email_messages:
            try:
                self._send_via_brevo(message)
                sent_count += 1
            except Exception as e:
                if not self.fail_silently:
                    raise
        return sent_count

    def _send_via_brevo(self, message):
        """Send a single email via Brevo API."""

        # Build recipient list
        to_list = [{'email': addr} for addr in message.to]
        cc_list = [{'email': addr} for addr in (message.cc or [])]
        bcc_list = [{'email': addr} for addr in (message.bcc or [])]

        # Get sender — Brevo requires verified/domain-authenticated senders.
        # Avoid @gmail.com senders: Gmail's DMARC policy rejects them when sent
        # through Brevo (deliverability: 0%). Use a domain you own instead.
        from_email = message.from_email or settings.DEFAULT_FROM_EMAIL
        brevo_sender = getattr(settings, 'BREVO_SENDER_EMAIL', '')
        if brevo_sender:
            sender_email = brevo_sender
        else:
            if '<' in from_email and '>' in from_email:
                sender_email = from_email[from_email.find('<')+1:from_email.find('>')]
            else:
                sender_email = from_email

        # Warn clearly in logs if using a public email provider as sender
        sender_domain = sender_email.split('@')[-1].lower()
        if sender_domain in ('gmail.com', 'googlemail.com', 'yahoo.com', 'outlook.com', 'hotmail.com', 'live.com'):
            _log.warning(
                f"Sending from public email {sender_email} via Brevo. "
                "This usually fails DMARC and lands in spam or is dropped. "
                "Set BREVO_SENDER_EMAIL to a domain-authenticated address like "
                f"noreply@{getattr(settings, 'BREVO_SENDER_DOMAIN', 'yourdomain.com')}."
            )

        sender = {'name': 'GPSL Business Suite', 'email': sender_email}

        # Build payload
        payload = {
            'sender': sender,
            'to': to_list,
            'subject': message.subject,
        }

        if cc_list:
            payload['cc'] = cc_list
        if bcc_list:
            payload['bcc'] = bcc_list

        # Handle HTML vs plain text
        body = message.body
        content_type = getattr(message, 'content_subtype', 'plain')

        if content_type == 'html' or '<html' in body.lower() or '<div' in body.lower():
            payload['htmlContent'] = body
            payload['textContent'] = 'Please view this email in an HTML-compatible email client.'
        else:
            payload['textContent'] = body
            # Check for HTML alternatives
            if hasattr(message, 'alternatives'):
                for content, mimetype in message.alternatives:
                    if mimetype == 'text/html':
                        payload['htmlContent'] = content
                        break

        # Make the API request
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            self.api_url,
            data=data,
            headers={
                'accept': 'application/json',
                'api-key': self.api_key,
                'content-type': 'application/json',
            },
            method='POST'
        )

        import logging as _logging
        _log = _logging.getLogger('django.security')
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                resp_body = response.read().decode('utf-8')
                if response.status in (200, 201):
                    _log.info(f"Brevo email accepted: {resp_body[:200]}")
                else:
                    _log.warning(f"Brevo API non-2xx: {response.status} body={resp_body[:300]}")
                    raise Exception(f'Brevo API error {response.status}: {resp_body}')
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8') if e.fp else str(e)
            _log.error(f"Brevo API FAILED: HTTP {e.code} body={error_body[:300]}")
            raise Exception(f'Brevo API HTTP error {e.code}: {error_body}')
