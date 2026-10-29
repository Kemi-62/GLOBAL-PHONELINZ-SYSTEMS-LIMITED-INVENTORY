# ROLES_V1
from django import template

from core.roles import has_role as _has_role

register = template.Library()


@register.filter(name="has_role")
def has_role_filter(user, names):
    """{% if user|has_role:"RETAIL" %}  (comma separated names allowed)"""
    return _has_role(user, *[n.strip() for n in str(names).split(",") if n.strip()])


_BADGES = {
    "RETAIL_TELECOM": "RETAIL + TELECOM",
    "RETAIL_LEAD": "RETAIL LEAD",
    "SUB_DIRECTOR": "SUB DIRECTOR",
}


@register.filter(name="role_badge")
def role_badge(user):
    """Short text for the role badge in the top bar."""
    role = getattr(user, "role", "") or ""
    return _BADGES.get(role, role)
