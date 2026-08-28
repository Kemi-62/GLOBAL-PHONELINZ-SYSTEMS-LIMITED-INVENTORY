from django import template
from datetime import date as _date

register = template.Library()


@register.inclusion_tag('partials/staff_monthly_history.html', takes_context=True)
def staff_monthly_history(context):
    request = context['request']
    user = request.user
    from core.models import StaffMonthlyPerformanceArchive

    all_months = list(
        StaffMonthlyPerformanceArchive.objects.filter(staff=user)
        .order_by("-month").values_list("month", flat=True)
    )

    compare_a_str = request.GET.get("my_month_a", "")
    compare_b_str = request.GET.get("my_month_b", "")

    def _row(month_val):
        if not month_val:
            return None
        try:
            m = _date.fromisoformat(month_val)
        except ValueError:
            return None
        return StaffMonthlyPerformanceArchive.objects.filter(staff=user, month=m).first()

    if not compare_a_str and len(all_months) >= 1:
        compare_a_str = all_months[0].isoformat()
    if not compare_b_str and len(all_months) >= 2:
        compare_b_str = all_months[1].isoformat()

    row_a = _row(compare_a_str)
    row_b = _row(compare_b_str)

    def _pct(new_val, old_val):
        if not old_val:
            return None
        return round(((float(new_val) - float(old_val)) / float(old_val)) * 100, 1)

    comparison = None
    if row_a and row_b:
        comparison = {
            "a": row_a, "b": row_b,
            "revenue_change": _pct(row_a.total_revenue, row_b.total_revenue),
        }

    history = list(
        StaffMonthlyPerformanceArchive.objects.filter(staff=user).order_by("-month")[:12]
    )

    return {
        "my_history": history,
        "my_all_months": all_months,
        "my_compare_a": compare_a_str,
        "my_compare_b": compare_b_str,
        "my_comparison": comparison,
        "has_my_history": len(all_months) > 0,
    }
