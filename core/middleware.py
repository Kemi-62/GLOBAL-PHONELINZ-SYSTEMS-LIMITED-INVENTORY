"""
Security middleware for GPSL ERP.
- Rate limiting for login attempts (brute-force protection)
- Session timeout (auto-logout after inactivity)
- Security headers
- Admin access logging
"""

import time
import hashlib
import logging
from django.conf import settings
from django.http import HttpResponseForbidden, JsonResponse
from django.contrib import messages
from django.shortcuts import redirect
from django.core.cache import cache

security_logger = logging.getLogger('django.security')


def _hash_ip(ip: str) -> str:
    """One-way hash of IP for privacy-compliant logging."""
    return hashlib.sha256(ip.encode()).hexdigest()[:16]


class SecurityHeadersMiddleware:
    """Add security headers to every response."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        # Already set by Django, but double-ensure
        response['X-Content-Type-Options'] = 'nosniff'
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response['Permissions-Policy'] = 'geolocation=(self), camera=(self)'
        return response


class RateLimitMiddleware:
    """
    Rate limit login attempts to prevent brute-force attacks.
    Tracks failed attempts by IP + username combination.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Only check POST requests to login endpoint
        if request.method == 'POST' and request.path in ['/accounts/login/', '/']:
            ip = self._get_client_ip(request)
            username = request.POST.get('username', '').strip().lower()

            if username:
                key = f'ratelimit:{ip}:{username}'
                block_key = f'ratelimit_block:{ip}:{username}'

                # Check if currently blocked
                if cache.get(block_key):
                    security_logger.warning(
                        f"Blocked login attempt from ip_hash={_hash_ip(ip)} for user={username}"
                    )
                    return HttpResponseForbidden(
                        "Too many failed login attempts. Please try again in 30 minutes."
                    )

                # Check attempt count
                attempts = cache.get(key, 0)
                if attempts >= getattr(settings, 'RATE_LIMIT_LOGIN_ATTEMPTS', 5):
                    # Block for 30 minutes
                    cache.set(block_key, True, getattr(settings, 'RATE_LIMIT_LOGIN_BLOCK', 1800))
                    cache.delete(key)
                    security_logger.warning(
                        f"Rate limit exceeded for ip_hash={_hash_ip(ip)}/user={username}. Blocked for 30min."
                    )
                    return HttpResponseForbidden(
                        "Too many failed login attempts. Please try again in 30 minutes."
                    )

        response = self.get_response(request)

        # Track failed login attempts
        if request.method == 'POST' and request.path in ['/accounts/login/', '/']:
            if hasattr(response, 'status_code') and response.status_code in [200, 302]:
                # Check if this was a failed login (stays on login page with error)
                if hasattr(request, '_failed_login'):
                    ip = self._get_client_ip(request)
                    username = request.POST.get('username', '').strip().lower()
                    if username:
                        key = f'ratelimit:{ip}:{username}'
                        attempts = cache.get(key, 0) + 1
                        cache.set(key, attempts, getattr(settings, 'RATE_LIMIT_LOGIN_WINDOW', 300))
                        security_logger.info(
                            f"Failed login #{attempts} from ip_hash={_hash_ip(ip)} for user={username}"
                        )

        return response

    def _get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR', 'unknown')
        return ip


class SessionTimeoutMiddleware:
    """
    Auto-logout after inactivity.
    Resets timer on every request.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            if request.user.is_authenticated:
                last_activity = request.session.get('last_activity')
                now = time.time()

                if last_activity:
                    max_inactive = getattr(settings, 'SESSION_COOKIE_AGE', 28800)
                    if now - last_activity > max_inactive:
                        from django.contrib.auth import logout
                        logout(request)
                        messages.info(request, "Your session expired due to inactivity. Please log in again.")
                        return redirect('login')

                request.session['last_activity'] = now
        except AttributeError:
            pass  # request.user not available yet

        return self.get_response(request)


class AdminAccessLogMiddleware:
    """
    Log all admin panel access attempts for security monitoring.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        admin_url = getattr(settings, 'ADMIN_URL', 'admin/')
        if request.path.startswith(f'/{admin_url}'):
            ip = self._get_client_ip(request)
            user = request.user.username if request.user.is_authenticated else 'anonymous'
            security_logger.info(
                f"Admin access: path={request.path} user={user} ip_hash={_hash_ip(ip)} method={request.method}"
            )
        return self.get_response(request)

    def _get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', 'unknown')
