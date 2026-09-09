from django import template

register = template.Library()


@register.simple_tag
def mc_carried_forward_balance(user):
    from core.models import MultiChoiceWeeklyReport
    last_closed = MultiChoiceWeeklyReport.objects.filter(
        staff=user, is_closed=True
    ).order_by("-week_start_date").first()
    if last_closed and last_closed.closing_balance is not None:
        return last_closed.closing_balance
    return 0
