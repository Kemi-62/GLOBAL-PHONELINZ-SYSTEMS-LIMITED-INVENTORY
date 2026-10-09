"""STOCK_APPROVALS_V1 - sidebar badge: how many stock approvals are waiting for this user."""
from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def stock_approvals_count(context):
    user = context.get("user")
    if user is None:
        request = context.get("request")
        user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return 0
    from core.stock_approvals import pending_count
    return pending_count(user)
