
# ─────────────────────────────────────────
# HARDER IMAGE COMPRESSION
# Replace the existing _compress_image function in views.py
# Target: 50KB max, 400px max dimension
# ─────────────────────────────────────────

import io as _io
from PIL import Image as _PILImage


def _compress_image(image_file, max_size_kb=50, max_dimension=400):
    """
    Compress uploaded selfie image aggressively.
    Target: 50KB max, 400px max — still clearly identifiable face.
    Down from previous 200KB / 800px.
    """
    try:
        img = _PILImage.open(image_file)
        # Convert to RGB
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        # Resize aggressively — faces are still clear at 400px
        w, h = img.size
        if w > max_dimension or h > max_dimension:
            img.thumbnail((max_dimension, max_dimension), _PILImage.LANCZOS)
        # Start at quality 70 and reduce until under max_size_kb
        output = _io.BytesIO()
        quality = 70
        while quality >= 30:
            output.seek(0)
            output.truncate()
            img.save(output, format="JPEG", quality=quality, optimize=True)
            if output.tell() / 1024 <= max_size_kb:
                break
            quality -= 10
        output.seek(0)
        from django.core.files.uploadedfile import InMemoryUploadedFile
        return InMemoryUploadedFile(
            output, "ImageField",
            image_file.name.rsplit(".", 1)[0] + ".jpg",
            "image/jpeg", output.getbuffer().nbytes, None
        )
    except Exception:
        return image_file


# ─────────────────────────────────────────
# UPDATED director_attendance_dashboard
# Current week: shows selfie thumbnails
# Older records: no images, icon only
# ─────────────────────────────────────────

@role_required("DIRECTOR")
def director_attendance_dashboard(request):
    from datetime import date as _date, timedelta as _td
    selected_date_str = request.GET.get("date", "")
    branch_filter     = request.GET.get("branch", "")
    staff_filter      = request.GET.get("staff", "")
    today             = _date.today()

    # Current week Monday
    week_start = today - _td(days=today.weekday())

    # Determine if we are viewing current week
    if selected_date_str:
        try:
            selected_date = _date.fromisoformat(selected_date_str)
        except Exception:
            selected_date = today
    else:
        selected_date = today

    is_current_week = (selected_date >= week_start)

    records = Attendance.objects.filter(
        date=selected_date
    ).select_related("user", "branch").order_by("branch__name", "user__username")

    if branch_filter:
        records = records.filter(branch_id=branch_filter)
    if staff_filter:
        records = records.filter(user_id=staff_filter)

    all_staff = User.objects.exclude(
        role__in=["DIRECTOR", "SUPERADMIN"]
    ).select_related("branch").order_by("branch__name", "username")

    return render(request, "director/attendance.html", {
        "records": records,
        "selected_date": selected_date,
        "selected_branch": branch_filter,
        "selected_staff": staff_filter,
        "branches": Branch.objects.all(),
        "all_staff": all_staff,
        "is_current_week": is_current_week,
        "week_start": week_start,
        "today": today,
        "total_ontime": records.filter(is_late=False, is_absent=False).count(),
        "total_late": records.filter(is_late=True).count(),
        "total_absent": records.filter(is_absent=True).count(),
        "total_deductions": records.aggregate(
            Sum("deduction_amount")
        )["deduction_amount__sum"] or 0,
    })
