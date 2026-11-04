"""MC_PRICING_V1: how the amount collected from the customer is worked out.

Change MARKUP here and every new MultiChoice subscription follows it.
"""
from decimal import Decimal

MARKUP = Decimal("200")

CATEGORIES = (
    ("CUSTOMER", "Customer subscription"),
    ("ACTIVATION", "Activation (recorded at cost)"),
    ("OFFICE", "Office subscription (recorded at cost)"),
    ("DIRECTOR", "Given by Director (recorded at cost)"),
)
AT_COST = {"ACTIVATION", "OFFICE", "DIRECTOR"}
NOT_CUSTOMERS = set()   # every sale type counts as a real customer (CRM and renewal reminders)


def amount_for(cost_price, category):
    cost = Decimal(cost_price or 0)
    return cost if category in AT_COST else cost + MARKUP


def clean_category(value):
    return value if value in dict(CATEGORIES) else "CUSTOMER"


def markup_for(category):
    """The part of the amount that is the business's service charge (never commission)."""
    return Decimal("0") if category in AT_COST else MARKUP
