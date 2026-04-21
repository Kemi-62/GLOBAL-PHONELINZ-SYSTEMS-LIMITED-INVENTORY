
# ─────────────────────────────────────────
# FIXED STAFF CHECKOUT — gets staff_id from POST not URL
# ─────────────────────────────────────────

@role_required("MANAGER")
def staff_checkout(request, staff_id=None):
    if request.method == "POST":
        sid = request.POST.get("staff_id") or staff_id
        if not sid or str(sid) == "0":
            messages.error(request, "Please select a staff member.")
            return redirect("manager_dashboard")
        staff = get_object_or_404(User, id=sid, branch=request.user.branch)
        purpose = request.POST.get("purpose", "Office outing")
        CheckInOutLog.objects.create(
            staff=staff,
            branch=request.user.branch,
            check_in_time=timezone.now(),
            purpose=purpose,
            is_checkout=True,
        )
        messages.success(request, f"{staff.username} checked out for: {purpose}")
    return redirect("manager_dashboard")


@role_required("MANAGER")
def staff_checkin(request, staff_id):
    log = CheckInOutLog.objects.filter(
        staff_id=staff_id, branch=request.user.branch,
        is_checkout=True, check_out_time__isnull=True
    ).last()
    if log:
        log.check_out_time = timezone.now()
        log.save()
        messages.success(request, f"{log.staff.username} is back.")
    else:
        messages.warning(request, "No active outing found for this staff.")
    return redirect("manager_dashboard")


# ─────────────────────────────────────────
# FIXED CHECK-IN with inline JSON response handler
# Returns JSON for AJAX, renders nice page on direct POST
# ─────────────────────────────────────────

import io as _io
from PIL import Image as _PILImage


def _compress_image(image_file, max_size_kb=200, max_dimension=800):
    """Compress uploaded image to reduce storage size."""
    try:
        img = _PILImage.open(image_file)
        # Convert RGBA to RGB if needed
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        # Resize if too large
        w, h = img.size
        if w > max_dimension or h > max_dimension:
            img.thumbnail((max_dimension, max_dimension), _PILImage.LANCZOS)
        # Save compressed
        output = _io.BytesIO()
        quality = 85
        while True:
            output.seek(0)
            output.truncate()
            img.save(output, format="JPEG", quality=quality, optimize=True)
            size_kb = output.tell() / 1024
            if size_kb <= max_size_kb or quality <= 40:
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
        return image_file  # fallback to original if PIL fails


@login_required
def check_in(request):
    if request.method == "POST":
        user = request.user
        branch = user.branch
        if not branch or not branch.latitude or not branch.longitude:
            msg = "Branch location not configured. Contact your director."
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"error": msg})
            messages.error(request, msg)
            return redirect(_get_dashboard_url(user))

        try:
            latitude = float(request.POST.get("latitude"))
            longitude = float(request.POST.get("longitude"))
        except (TypeError, ValueError):
            msg = "Could not read your location. Please enable GPS and try again."
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"error": msg})
            messages.error(request, msg)
            return redirect(_get_dashboard_url(user))

        selfie = request.FILES.get("selfie")
        today = timezone.now().date()

        if Attendance.objects.filter(user=user, date=today, session="morning").exists():
            msg = "You have already checked in today."
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"error": msg})
            messages.warning(request, msg)
            return redirect(_get_dashboard_url(user))

        distance = calculate_distance(latitude, longitude, branch.latitude, branch.longitude)
        if distance > branch.allowed_radius:
            msg = f"You are {distance:.0f}m away from your branch. Allowed radius is {branch.allowed_radius}m."
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"error": msg, "distance": round(distance, 2)})
            messages.error(request, msg)
            return redirect(_get_dashboard_url(user))

        status = attendance_status()
        if selfie:
            selfie = _compress_image(selfie)

        attendance = Attendance(
            user=user, branch=branch, session="morning",
            check_in_time=timezone.now(),
            latitude=latitude, longitude=longitude,
            distance_from_branch=distance, selfie=selfie,
        )
        if status == "late":
            attendance.is_late = True
            attendance.deduction_amount = Decimal("250.00")
        elif status == "absent":
            attendance.is_absent = True
        attendance.save()

        msg = "Check-in successful! You are " + ("on time." if status == "ontime" else "marked late." if status == "late" else "recorded.")
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": msg})
        messages.success(request, msg)
        return redirect(_get_dashboard_url(user))

    return render(request, "staff/attendance.html")


@login_required
def check_out(request):
    if request.method == "POST":
        user = request.user
        branch = user.branch
        if not branch or not branch.latitude or not branch.longitude:
            msg = "Branch location not configured. Contact your director."
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"error": msg})
            messages.error(request, msg)
            return redirect(_get_dashboard_url(user))

        try:
            latitude = float(request.POST.get("latitude"))
            longitude = float(request.POST.get("longitude"))
        except (TypeError, ValueError):
            msg = "Could not read your location. Please enable GPS and try again."
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"error": msg})
            messages.error(request, msg)
            return redirect(_get_dashboard_url(user))

        selfie = request.FILES.get("selfie")
        today = timezone.now().date()

        attendance = Attendance.objects.filter(user=user, date=today, session="morning").first()
        if not attendance:
            msg = "No morning check-in found for today. Please check in first."
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"error": msg})
            messages.error(request, msg)
            return redirect(_get_dashboard_url(user))

        if attendance.check_out_time:
            msg = "You have already checked out today."
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"error": msg})
            messages.warning(request, msg)
            return redirect(_get_dashboard_url(user))

        distance = calculate_distance(latitude, longitude, branch.latitude, branch.longitude)
        if distance > branch.allowed_radius:
            msg = f"You are {distance:.0f}m away from your branch. Allowed radius is {branch.allowed_radius}m."
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"error": msg})
            messages.error(request, msg)
            return redirect(_get_dashboard_url(user))

        if selfie:
            selfie = _compress_image(selfie)
            attendance.selfie = selfie
        attendance.check_out_time = timezone.now()
        attendance.save()

        msg = "Check-out successful! Have a great evening."
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": msg})
        messages.success(request, msg)
        return redirect(_get_dashboard_url(user))

    return redirect(_get_dashboard_url(request.user))


def _get_dashboard_url(user):
    """Return the dashboard URL name for a given user's role."""
    mapping = {
        "DIRECTOR": "director_dashboard",
        "MANAGER": "manager_dashboard",
        "RETAIL": "retail_dashboard",
        "MULTICHOICE": "multichoice_dashboard",
        "TELECOM": "staff_dashboard",
    }
    return mapping.get(getattr(user, "role", None), "login")


# ─────────────────────────────────────────
# FIXED RETAIL CSV UPLOAD — handles BOM, flexible headers
# ─────────────────────────────────────────

@role_required("RETAIL")
def upload_retail_csv(request):
    if request.method == "POST":
        csv_file = request.FILES.get("csv_file")
        if not csv_file:
            messages.error(request, "No file uploaded.")
            return redirect("retail_dashboard")
        if not csv_file.name.lower().endswith(".csv"):
            messages.error(request, "Please upload a .csv file only.")
            return redirect("retail_dashboard")
        if csv_file.size > 5 * 1024 * 1024:
            messages.error(request, "File too large. Maximum 5MB.")
            return redirect("retail_dashboard")
        try:
            raw = csv_file.read()
            # Handle BOM (Excel-generated CSVs often have this)
            decoded = raw.decode("utf-8-sig").splitlines()
            # Strip blank lines
            decoded = [l for l in decoded if l.strip()]
            if not decoded:
                messages.error(request, "CSV file is empty.")
                return redirect("retail_dashboard")

            reader = csv.DictReader(decoded)
            # Normalize headers — strip spaces and lowercase
            reader.fieldnames = [f.strip().lower().replace(" ", "_") for f in (reader.fieldnames or [])]

            count = 0
            errors = []
            for i, row in enumerate(reader, start=2):
                # Clean all values
                row = {k: (v or "").strip() for k, v in row.items()}
                model_name = row.get("model_name", "")
                if not model_name:
                    errors.append(f"Row {i}: model_name is empty")
                    continue
                try:
                    category_name = row.get("category", "General") or "General"
                    subcategory_name = row.get("subcategory", "General") or "General"
                    selling_price = float(row.get("selling_price", 0) or 0)
                    cost_price = float(row.get("cost_price", 0) or 0)
                    quantity = int(row.get("quantity", 1) or 1)
                    imei = row.get("imei_serial", "") or None

                    category, _ = RetailCategory.objects.get_or_create(name=category_name)
                    subcategory, _ = RetailSubCategory.objects.get_or_create(
                        category=category, name=subcategory_name
                    )
                    product, created = Product.objects.get_or_create(
                        model_name=model_name,
                        defaults={
                            "subcategory": subcategory,
                            "product_name": row.get("product_name", "") or model_name,
                            "description": row.get("description", "") or "",
                            "imei_serial": imei,
                            "cost_price": cost_price,
                            "selling_price": selling_price,
                        }
                    )
                    if not created and selling_price:
                        product.selling_price = selling_price
                        product.save(update_fields=["selling_price"])

                    with transaction.atomic():
                        stock, _ = StaffStock.objects.get_or_create(
                            staff=request.user, product=product
                        )
                        stock.quantity += quantity
                        stock.save()
                    count += 1
                except Exception as e:
                    errors.append(f"Row {i}: {e}")

            if count:
                msg = f"✓ Successfully uploaded {count} product(s) to your catalog."
                if errors:
                    msg += f" {len(errors)} row(s) skipped."
                messages.success(request, msg)
            else:
                msg = f"No products were uploaded. {len(errors)} error(s): " + "; ".join(errors[:5])
                messages.error(request, msg)
        except Exception as e:
            messages.error(request, f"Could not read file: {e}")
    return redirect("retail_dashboard")


# ─────────────────────────────────────────
# FIXED MANAGER CSV UPLOAD
# ─────────────────────────────────────────

@role_required("MANAGER")
def upload_manager_csv(request):
    if request.method == "POST":
        csv_file = request.FILES.get("csv_file")
        if not csv_file:
            messages.error(request, "No file uploaded.")
            return redirect("manager_dashboard")
        if not csv_file.name.lower().endswith(".csv"):
            messages.error(request, "Please upload a .csv file only.")
            return redirect("manager_dashboard")
        try:
            branch = request.user.branch
            raw = csv_file.read()
            decoded = raw.decode("utf-8-sig").splitlines()
            decoded = [l for l in decoded if l.strip()]
            reader = csv.DictReader(decoded)
            reader.fieldnames = [f.strip().lower().replace(" ", "_") for f in (reader.fieldnames or [])]

            count = 0
            errors = []
            for i, row in enumerate(reader, start=2):
                row = {k: (v or "").strip() for k, v in row.items()}
                model_name = row.get("model_name", "")
                if not model_name:
                    errors.append(f"Row {i}: model_name is empty")
                    continue
                try:
                    category_name = row.get("category", "General") or "General"
                    subcategory_name = row.get("subcategory", "General") or "General"
                    quantity = int(row.get("quantity", 0) or 0)
                    cost_price = float(row.get("cost_price", 0) or 0)
                    selling_price = float(row.get("selling_price", 0) or 0)
                    imei = row.get("imei_serial", "") or None

                    category, _ = RetailCategory.objects.get_or_create(name=category_name)
                    subcategory, _ = RetailSubCategory.objects.get_or_create(
                        category=category, name=subcategory_name
                    )
                    product, created = Product.objects.get_or_create(
                        model_name=model_name,
                        defaults={
                            "subcategory": subcategory,
                            "product_name": row.get("product_name", "") or model_name,
                            "description": "",
                            "imei_serial": imei,
                            "cost_price": cost_price,
                            "selling_price": selling_price,
                        }
                    )
                    if not created and (cost_price or selling_price):
                        if cost_price: product.cost_price = cost_price
                        if selling_price: product.selling_price = selling_price
                        product.save(update_fields=["cost_price", "selling_price"])

                    with transaction.atomic():
                        safe_stock, _ = BranchSafeStock.objects.get_or_create(
                            branch=branch, product=product
                        )
                        safe_stock.quantity += quantity
                        safe_stock.save()
                        StockMovement.objects.create(
                            branch=branch, product=product,
                            quantity=quantity, movement_type="IN",
                            performed_by=request.user,
                        )
                    count += 1
                except Exception as e:
                    errors.append(f"Row {i}: {e}")

            if count:
                msg = f"✓ Imported {count} product(s) to branch safe."
                if errors: msg += f" {len(errors)} skipped."
                messages.success(request, msg)
            else:
                messages.error(request, "No products imported. Errors: " + "; ".join(errors[:5]))
        except Exception as e:
            messages.error(request, f"Could not read file: {e}")
    return redirect("manager_dashboard")


# ─────────────────────────────────────────
# FIXED DIRECTOR CSV UPLOAD
# ─────────────────────────────────────────

@role_required("DIRECTOR")
def upload_director_csv(request):
    if request.method == "POST":
        csv_file = request.FILES.get("csv_file")
        if not csv_file:
            messages.error(request, "No file uploaded.")
            return redirect("director_safe_stock")
        if not csv_file.name.lower().endswith(".csv"):
            messages.error(request, "Please upload a .csv file only.")
            return redirect("director_safe_stock")
        try:
            raw = csv_file.read()
            decoded = raw.decode("utf-8-sig").splitlines()
            decoded = [l for l in decoded if l.strip()]
            reader = csv.DictReader(decoded)
            reader.fieldnames = [f.strip().lower().replace(" ", "_") for f in (reader.fieldnames or [])]

            count = 0
            errors = []
            for i, row in enumerate(reader, start=2):
                row = {k: (v or "").strip() for k, v in row.items()}
                model_name = row.get("model_name", "")
                if not model_name:
                    errors.append(f"Row {i}: model_name is empty")
                    continue
                try:
                    category_name = row.get("category", "General") or "General"
                    subcategory_name = row.get("subcategory", "General") or "General"
                    quantity = int(row.get("quantity", 0) or 0)
                    cost_price = float(row.get("cost_price", 0) or 0)
                    selling_price = float(row.get("selling_price", 0) or 0)
                    imei = row.get("imei_serial", "") or None

                    category, _ = RetailCategory.objects.get_or_create(name=category_name)
                    subcategory, _ = RetailSubCategory.objects.get_or_create(
                        category=category, name=subcategory_name
                    )
                    product, created = Product.objects.get_or_create(
                        model_name=model_name,
                        defaults={
                            "subcategory": subcategory,
                            "product_name": row.get("product_name", "") or model_name,
                            "description": "",
                            "imei_serial": imei,
                            "cost_price": cost_price,
                            "selling_price": selling_price,
                        }
                    )
                    if not created and (cost_price or selling_price):
                        if cost_price: product.cost_price = cost_price
                        if selling_price: product.selling_price = selling_price
                        product.save(update_fields=["cost_price", "selling_price"])

                    with transaction.atomic():
                        existing = DirectorSafeStock.objects.filter(product=product).first()
                        if existing:
                            existing.quantity += quantity
                            existing.save()
                        else:
                            DirectorSafeStock.objects.create(
                                product=product, quantity=quantity, notes="Bulk uploaded"
                            )
                    count += 1
                except Exception as e:
                    errors.append(f"Row {i}: {e}")

            if count:
                msg = f"✓ Imported {count} product(s) to director safe."
                if errors: msg += f" {len(errors)} skipped."
                messages.success(request, msg)
            else:
                messages.error(request, "No products imported. Errors: " + "; ".join(errors[:5]))
        except Exception as e:
            messages.error(request, f"Could not read file: {e}")
    return redirect("director_safe_stock")


# ─────────────────────────────────────────
# DIRECTOR RELEASE STOCK
# ─────────────────────────────────────────

@role_required("DIRECTOR")
def director_release_stock(request):
    if request.method == "POST":
        product_id = request.POST.get("product_id")
        quantity = int(request.POST.get("quantity", 0))
        release_type = request.POST.get("release_type")
        branch_id = request.POST.get("branch_id")
        staff_id = request.POST.get("staff_id")

        director_stock = get_object_or_404(DirectorSafeStock, product_id=product_id)

        if quantity <= 0:
            messages.error(request, "Quantity must be greater than 0.")
            return redirect("director_safe_stock")

        if quantity > director_stock.quantity:
            messages.error(request, f"Only {director_stock.quantity} unit(s) available.")
            return redirect("director_safe_stock")

        with transaction.atomic():
            director_stock.quantity -= quantity
            if director_stock.quantity == 0:
                director_stock.delete()
            else:
                director_stock.save()

            if release_type == "sale":
                messages.success(request, f"Recorded direct sale of {quantity} unit(s) from director safe.")

            elif release_type == "branch_safe":
                branch = get_object_or_404(Branch, id=branch_id)
                safe_stock, _ = BranchSafeStock.objects.get_or_create(branch=branch, product_id=product_id)
                safe_stock.quantity += quantity
                safe_stock.save()
                StockMovement.objects.create(
                    branch=branch, product_id=product_id,
                    quantity=quantity, movement_type="IN", performed_by=request.user,
                )
                messages.success(request, f"Released {quantity} unit(s) to {branch.name} safe.")

            elif release_type == "staff":
                staff = get_object_or_404(User, id=staff_id)
                staff_stock, _ = StaffStock.objects.get_or_create(staff=staff, product_id=product_id)
                staff_stock.quantity += quantity
                staff_stock.save()
                messages.success(request, f"Released {quantity} unit(s) directly to {staff.username}.")

    return redirect("director_safe_stock")
