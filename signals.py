from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.utils import timezone

LOW_STOCK_THRESHOLD = 3


# ─────────────────────────────────────────
# AUTO STOCK ALERTS + EMAIL
# ─────────────────────────────────────────

@receiver(post_save, sender='core.BranchSafeStock')
def check_stock_alert(sender, instance, **kwargs):
    from core.models import StockAlert, Notification
    from django.contrib.auth import get_user_model
    User = get_user_model()

    try:
        if instance.quantity <= 0:
            StockAlert.objects.update_or_create(
                product=instance.product, branch=instance.branch,
                defaults={
                    'alert_type': 'OUT_OF_STOCK',
                    'current_quantity': instance.quantity,
                    'threshold': LOW_STOCK_THRESHOLD,
                    'is_active': True,
                }
            )
            # In-app notification to managers
            for mgr in User.objects.filter(branch=instance.branch, role='MANAGER'):
                Notification.objects.update_or_create(
                    recipient=mgr,
                    notif_type='LOW_STOCK',
                    title=f'{instance.product.model_name} is OUT OF STOCK',
                    defaults={
                        'message': (
                            f'{instance.product.model_name} has reached 0 units '
                            f'in {instance.branch.name} safe.'
                        ),
                        'link': '/stock-alerts/',
                        'is_read': False,
                    }
                )
            # Email alert
            try:
                from core.views import send_stock_alert_email
                send_stock_alert_email(
                    product_name=instance.product.model_name,
                    branch_name=instance.branch.name,
                    quantity=0,
                    alert_type='OUT_OF_STOCK',
                )
            except Exception:
                pass

        elif instance.quantity <= LOW_STOCK_THRESHOLD:
            StockAlert.objects.update_or_create(
                product=instance.product, branch=instance.branch,
                defaults={
                    'alert_type': 'LOW_STOCK',
                    'current_quantity': instance.quantity,
                    'threshold': LOW_STOCK_THRESHOLD,
                    'is_active': True,
                }
            )
            # Email alert for low stock
            try:
                from core.views import send_stock_alert_email
                send_stock_alert_email(
                    product_name=instance.product.model_name,
                    branch_name=instance.branch.name,
                    quantity=instance.quantity,
                    alert_type='LOW_STOCK',
                )
            except Exception:
                pass
        else:
            # Stock is healthy - clear alert
            StockAlert.objects.filter(
                product=instance.product, branch=instance.branch
            ).update(is_active=False)

    except Exception:
        pass


# ─────────────────────────────────────────
# NOTIFY DIRECTOR ON STOCK REQUEST
# ─────────────────────────────────────────

@receiver(post_save, sender='core.StockRequest')
def notify_on_stock_request(sender, instance, created, **kwargs):
    if not created:
        return
    try:
        from core.models import Notification
        from django.contrib.auth import get_user_model
        User = get_user_model()
        for director in User.objects.filter(role='DIRECTOR'):
            Notification.objects.create(
                recipient=director,
                notif_type='STOCK_REQUEST',
                title=f'Stock request from {instance.branch.name}',
                message=(
                    f'{instance.staff.username} requested '
                    f'{instance.quantity} x {instance.product_name}.'
                ),
                link='/manager/',
            )
        for mgr in User.objects.filter(role='MANAGER', branch=instance.branch):
            Notification.objects.create(
                recipient=mgr,
                notif_type='STOCK_REQUEST',
                title='New stock request',
                message=(
                    f'{instance.staff.username} requested '
                    f'{instance.quantity} x {instance.product_name}.'
                ),
                link='/manager/',
            )
    except Exception:
        pass


# ─────────────────────────────────────────
# NOTIFY MANAGER ON PENDING TELECOM APPROVAL
# ─────────────────────────────────────────

@receiver(post_save, sender='core.ServiceActivity')
def notify_on_approval_needed(sender, instance, created, **kwargs):
    if not created or not instance.requires_approval:
        return
    try:
        from core.models import Notification
        from django.contrib.auth import get_user_model
        User = get_user_model()
        for mgr in User.objects.filter(role='MANAGER', branch=instance.branch):
            Notification.objects.create(
                recipient=mgr,
                notif_type='APPROVAL',
                title='Activity needs approval',
                message=(
                    f'{instance.staff.username} exceeded target for '
                    f'{instance.service_type}. Approval needed.'
                ),
                link='/manager/',
            )
    except Exception:
        pass
