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

        # Get sender
        from_email = message.from_email or settings.DEFAULT_FROM_EMAIL
        # Parse "Name <email>" format
        if '<' in from_email and '>' in from_email:
            name_part = from_email[:from_email.find('<')].strip().strip('"')
            email_part = from_email[from_email.find('<')+1:from_email.find('>')]
            sender = {'name': name_part, 'email': email_part}
        else:
            sender = {'name': 'GPSL Business Suite', 'email': from_email}

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

        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                resp_body = response.read().decode('utf-8')
                if response.status not in (200, 201):
                    raise Exception(f'Brevo API error {response.status}: {resp_body}')
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8') if e.fp else str(e)
            raise Exception(f'Brevo API HTTP error {e.code}: {error_body}')
