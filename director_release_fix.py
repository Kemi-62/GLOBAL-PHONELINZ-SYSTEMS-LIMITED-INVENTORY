
# ─────────────────────────────────────────
# FIXED director_release_stock
# Adds to existing stock, logs every release
# ─────────────────────────────────────────

@role_required("DIRECTOR")
def director_release_stock(request):
    if request.method == "POST":
        product_id   = request.POST.get("product_id")
        quantity     = int(request.POST.get("quantity", 0))
        release_type = request.POST.get("release_type")
        branch_id    = request.POST.get("branch_id")
        staff_id     = request.POST.get("staff_id")

        if not product_id:
            messages.error(request, "Please select a product.")
            return redirect("director_safe_stock")

        director_stock = DirectorSafeStock.objects.filter(
            product_id=product_id
        ).first()

        if not director_stock:
            messages.error(request, "Product not found in director safe.")
            return redirect("director_safe_stock")

        if quantity <= 0:
            messages.error(request, "Quantity must be greater than 0.")
            return redirect("director_safe_stock")

        if quantity > director_stock.quantity:
            messages.error(
                request,
                f"Only {director_stock.quantity} unit(s) of "
                f"{director_stock.product.model_name} available in director safe."
            )
            return redirect("director_safe_stock")

        product = director_stock.product
        desc    = ""

        with transaction.atomic():
            # Reduce director safe
            director_stock.quantity -= quantity
            if director_stock.quantity == 0:
                director_stock.delete()
            else:
                director_stock.save()

            if release_type == "sale":
                desc = (
                    f"Director direct sale: {quantity}x {product.model_name}. "
                    f"Branch: {Branch.objects.filter(id=branch_id).first().name if branch_id else 'N/A'}."
                )
                messages.success(
                    request,
                    f"Recorded direct sale of {quantity}x {product.model_name} from director safe."
                )

            elif release_type == "branch_safe":
                if not branch_id:
                    messages.error(request, "Please select a branch.")
                    return redirect("director_safe_stock")
                branch = get_object_or_404(Branch, id=branch_id)

                # ADD to branch safe stock (not replace)
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
                desc = (
                    f"Released {quantity}x {product.model_name} from director safe "
                    f"to {branch.name} branch safe. New branch safe qty: {safe_stock.quantity}."
                )
                messages.success(request, desc)

            elif release_type == "staff":
                if not staff_id:
                    messages.error(request, "Please select a staff member.")
                    return redirect("director_safe_stock")
                staff = get_object_or_404(User, id=staff_id)

                # ADD to staff stock (not replace)
                staff_stock, _ = StaffStock.objects.get_or_create(
                    staff=staff, product=product
                )
                staff_stock.quantity += quantity
                staff_stock.save()

                desc = (
                    f"Released {quantity}x {product.model_name} from director safe "
                    f"directly to {staff.username} "
                    f"({staff.branch.name if staff.branch else 'No branch'}). "
                    f"Staff stock now: {staff_stock.quantity}."
                )
                messages.success(request, desc)

            else:
                messages.error(request, "Invalid release type selected.")
                return redirect("director_safe_stock")

            # Log to AuditLog
            try:
                from core.models import AuditLog
                AuditLog.objects.create(
                    user=request.user,
                    action="UPDATE",
                    model_name="DirectorSafeStock",
                    description=desc,
                )
            except Exception:
                pass

    return redirect("director_safe_stock")
