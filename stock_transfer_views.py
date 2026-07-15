

# ─────────────────────────────────────────
# STOCK TRANSFER — Branch to Branch, Director, Staff
# ─────────────────────────────────────────

@role_required("DIRECTOR", "MANAGER")
def stock_transfer(request):
    """Record a stock transfer between any two parties."""
    from core.models import (
        StockTransfer, DirectorSafeStock, BranchSafeStock,
        StaffStock, Product, Branch
    )
    from django.utils import timezone as _tz

    branches = Branch.objects.all()
    products = Product.objects.all().order_by('model_name')
    staff_list = User.objects.filter(
        role__in=['RETAIL', 'TELECOM', 'MULTICHOICE']
    ).order_by('username')

    # For managers, limit to their branch
    if request.user.role == 'MANAGER':
        staff_list = staff_list.filter(branch=request.user.branch)

    if request.method == 'POST':
        try:
            transfer_type = request.POST.get('transfer_type')
            product_id    = request.POST.get('product')
            quantity      = int(request.POST.get('quantity', 0))
            notes         = request.POST.get('notes', '').strip()
            from_branch_id = request.POST.get('from_branch') or None
            to_branch_id   = request.POST.get('to_branch') or None
            to_staff_id    = request.POST.get('to_staff') or None

            product  = get_object_or_404(Product, id=product_id)
            from_branch = Branch.objects.get(id=from_branch_id) if from_branch_id else None
            to_branch   = Branch.objects.get(id=to_branch_id) if to_branch_id else None
            to_staff    = User.objects.get(id=to_staff_id) if to_staff_id else None

            if quantity <= 0:
                messages.error(request, 'Quantity must be greater than 0.')
                return redirect('stock_transfer')

            # Deduct from source
            if transfer_type == 'DIRECTOR_TO_BRANCH':
                src = DirectorSafeStock.objects.filter(product=product).first()
                if not src or src.quantity < quantity:
                    messages.error(request, f'Insufficient stock in Director Safe. Available: {src.quantity if src else 0}')
                    return redirect('stock_transfer')
                src.quantity -= quantity
                src.save()
                # Add to branch
                dst, _ = BranchSafeStock.objects.get_or_create(product=product, branch=to_branch)
                dst.quantity += quantity
                dst.save()

            elif transfer_type == 'BRANCH_TO_BRANCH':
                src = BranchSafeStock.objects.filter(product=product, branch=from_branch).first()
                if not src or src.quantity < quantity:
                    messages.error(request, f'Insufficient stock in {from_branch.name}. Available: {src.quantity if src else 0}')
                    return redirect('stock_transfer')
                src.quantity -= quantity
                src.save()
                dst, _ = BranchSafeStock.objects.get_or_create(product=product, branch=to_branch)
                dst.quantity += quantity
                dst.save()

            elif transfer_type == 'BRANCH_TO_STAFF':
                src = BranchSafeStock.objects.filter(product=product, branch=from_branch).first()
                if not src or src.quantity < quantity:
                    messages.error(request, f'Insufficient stock in {from_branch.name}. Available: {src.quantity if src else 0}')
                    return redirect('stock_transfer')
                src.quantity -= quantity
                src.save()
                dst, _ = StaffStock.objects.get_or_create(product=product, staff=to_staff)
                dst.quantity += quantity
                dst.save()

            elif transfer_type == 'BRANCH_TO_DIRECTOR':
                src = BranchSafeStock.objects.filter(product=product, branch=from_branch).first()
                if not src or src.quantity < quantity:
                    messages.error(request, f'Insufficient stock in {from_branch.name}. Available: {src.quantity if src else 0}')
                    return redirect('stock_transfer')
                src.quantity -= quantity
                src.save()
                dst, _ = DirectorSafeStock.objects.get_or_create(product=product)
                dst.quantity += quantity
                dst.save()

            elif transfer_type == 'STAFF_TO_BRANCH':
                src = StaffStock.objects.filter(product=product, staff=to_staff).first()
                if not src or src.quantity < quantity:
                    messages.error(request, f'Insufficient stock with {to_staff.username}. Available: {src.quantity if src else 0}')
                    return redirect('stock_transfer')
                src.quantity -= quantity
                src.save()
                dst, _ = BranchSafeStock.objects.get_or_create(product=product, branch=to_branch)
                dst.quantity += quantity
                dst.save()

            # Record transfer
            StockTransfer.objects.create(
                transfer_type=transfer_type,
                product=product,
                quantity=quantity,
                status='COMPLETED',
                notes=notes,
                from_branch=from_branch,
                to_branch=to_branch,
                to_staff=to_staff,
                initiated_by=request.user,
                approved_by=request.user,
                completed_at=_tz.now(),
            )

            # Audit log
            try:
                AuditLog.objects.create(
                    user=request.user,
                    action='TRANSFER',
                    model_name='StockTransfer',
                    description=f"Transferred {quantity}x {product.model_name}: {from_branch.name if from_branch else 'Director'} → {to_branch.name if to_branch else (to_staff.username if to_staff else 'Director')}"
                )
            except Exception:
                pass

            messages.success(request, f"Transfer complete: {quantity}x {product.model_name} moved successfully.")
        except Exception as e:
            messages.error(request, f"Transfer failed: {e}")
        return redirect('stock_transfer')

    # Recent transfers
    transfers = StockTransfer.objects.select_related(
        'product', 'from_branch', 'to_branch', 'to_staff', 'initiated_by'
    ).order_by('-created_at')[:50]

    if request.user.role == 'MANAGER':
        transfers = transfers.filter(
            Q(from_branch=request.user.branch) | Q(to_branch=request.user.branch)
        )

    return render(request, 'stock_transfer.html', {
        'branches': branches,
        'products': products,
        'staff_list': staff_list,
        'transfers': transfers,
        'today': timezone.now().date(),
    })


@role_required("DIRECTOR")
def stock_transfer_history(request):
    """Director - full stock transfer history with filters."""
    from core.models import StockTransfer
    date_from   = request.GET.get('date_from', '')
    date_to     = request.GET.get('date_to', '')
    branch_flt  = request.GET.get('branch', '')
    type_flt    = request.GET.get('type', '')

    transfers = StockTransfer.objects.select_related(
        'product', 'from_branch', 'to_branch', 'to_staff', 'initiated_by'
    ).order_by('-created_at')

    if date_from:
        transfers = transfers.filter(created_at__date__gte=date_from)
    if date_to:
        transfers = transfers.filter(created_at__date__lte=date_to)
    if branch_flt:
        transfers = transfers.filter(
            Q(from_branch_id=branch_flt) | Q(to_branch_id=branch_flt)
        )
    if type_flt:
        transfers = transfers.filter(transfer_type=type_flt)

    from core.models import Branch
    return render(request, 'director/stock_transfer_history.html', {
        'transfers': transfers[:200],
        'branches': Branch.objects.all(),
        'date_from': date_from,
        'date_to': date_to,
        'branch_flt': branch_flt,
        'type_flt': type_flt,
        'transfer_types': StockTransfer.TRANSFER_TYPE_CHOICES,
    })
