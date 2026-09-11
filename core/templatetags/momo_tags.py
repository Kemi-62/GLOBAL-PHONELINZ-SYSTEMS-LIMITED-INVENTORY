from django import template

register = template.Library()


@register.simple_tag
def momo_has_history(user):
    from core.models import DailyMomoBalance
    return DailyMomoBalance.objects.filter(staff=user).exists()


@register.inclusion_tag('partials/momo_history.html', takes_context=True)
def momo_history_widget(context):
    request = context['request']
    user = request.user
    from core.models import DailyMomoBalance

    history = DailyMomoBalance.objects.filter(
        staff=user, is_closed=True
    ).order_by("-date")[:30]

    return {"momo_history": history}
