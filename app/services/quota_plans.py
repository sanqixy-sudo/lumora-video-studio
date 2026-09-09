from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.timezone import SHANGHAI_TZ, shanghai_now, utcnow
from app.models.tables import Job, JobQuotaReservation, PackageQuotaLedger, QuotaLedger, QuotaPlan, QuotaWallet, User, UserQuotaPlanAssignment
from app.services.jobs import add_event


PACKAGE_CHARGE_ACTION = "package_debit_create_success"
PACKAGE_REFUND_ACTION = "package_refund_failed_job"
PLAN_PERIOD_TYPES = {"daily", "weekly", "monthly"}


def quota_plan_period_label(period_type: str | None) -> str:
    return {
        "daily": "日套餐",
        "weekly": "周套餐",
        "monthly": "月套餐",
    }.get(str(period_type or ""), str(period_type or "-"))


def plan_quota_amount(plan: QuotaPlan, assignment: UserQuotaPlanAssignment | None = None) -> int:
    if assignment and assignment.custom_quota_amount is not None:
        return max(int(assignment.custom_quota_amount or 0), 0)
    return max(int(plan.quota_amount or 0), 0)


def _empty_quota_totals() -> dict[str, int]:
    return {
        "personal_remaining": 0,
        "personal_reserved": 0,
        "personal_available": 0,
        "package_remaining": 0,
        "package_reserved": 0,
        "package_available": 0,
        "total_remaining": 0,
        "total_reserved": 0,
        "total_available": 0,
    }


def quota_totals_for_users(db: Session, user_ids: list[int], wallets: dict[int, QuotaWallet | None] | None = None) -> dict[int, dict[str, int]]:
    ids = [int(user_id) for user_id in user_ids]
    totals = {user_id: _empty_quota_totals() for user_id in ids}
    if not ids:
        return totals

    wallet_map = wallets or {
        int(wallet.user_id): wallet
        for wallet in db.query(QuotaWallet).filter(QuotaWallet.user_id.in_(ids)).all()
    }
    for user_id in ids:
        wallet = wallet_map.get(user_id)
        if not wallet:
            continue
        remaining = int(wallet.remaining_quota or 0)
        reserved = int(wallet.reserved_quota or 0)
        totals[user_id]["personal_remaining"] = remaining
        totals[user_id]["personal_reserved"] = reserved
        totals[user_id]["personal_available"] = max(remaining - reserved, 0)

    rows = (
        db.query(UserQuotaPlanAssignment)
        .join(QuotaPlan, QuotaPlan.id == UserQuotaPlanAssignment.plan_id)
        .filter(UserQuotaPlanAssignment.user_id.in_(ids), UserQuotaPlanAssignment.status == "active", QuotaPlan.status == "active")
        .all()
    )
    for assignment in rows:
        user_id = int(assignment.user_id)
        remaining = int(assignment.remaining_quota or 0)
        reserved = int(assignment.reserved_quota or 0)
        totals[user_id]["package_remaining"] += remaining
        totals[user_id]["package_reserved"] += reserved
        totals[user_id]["package_available"] += max(remaining - reserved, 0)

    for values in totals.values():
        values["total_remaining"] = values["personal_remaining"] + values["package_remaining"]
        values["total_reserved"] = values["personal_reserved"] + values["package_reserved"]
        values["total_available"] = values["personal_available"] + values["package_available"]
    return totals


def quota_totals_for_user(db: Session, user_id: int, wallet: QuotaWallet | None = None) -> dict[str, int]:
    return quota_totals_for_users(db, [int(user_id)], {int(user_id): wallet} if wallet is not None else None)[int(user_id)]


def _ensure_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def period_bounds(period_type: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    local_now = now.astimezone(SHANGHAI_TZ) if now else shanghai_now()
    anchor_today = local_now.replace(hour=8, minute=0, second=0, microsecond=0)
    if period_type == "daily":
        current_start = anchor_today
        if local_now < current_start:
            current_start -= timedelta(days=1)
        return current_start.astimezone(UTC), (current_start + timedelta(days=1)).astimezone(UTC)

    if period_type == "monthly":
        current_start = local_now.replace(day=1, hour=8, minute=0, second=0, microsecond=0)
        if local_now < current_start:
            prev_month = 12 if current_start.month == 1 else current_start.month - 1
            prev_year = current_start.year - 1 if current_start.month == 1 else current_start.year
            current_start = current_start.replace(year=prev_year, month=prev_month, day=1)
        if current_start.month == 12:
            next_start = current_start.replace(year=current_start.year + 1, month=1, day=1)
        else:
            next_start = current_start.replace(month=current_start.month + 1, day=1)
        return current_start.astimezone(UTC), next_start.astimezone(UTC)

    monday = anchor_today - timedelta(days=anchor_today.weekday())
    if local_now < monday:
        monday -= timedelta(days=7)
    return monday.astimezone(UTC), (monday + timedelta(days=7)).astimezone(UTC)


def refresh_assignment_if_due(db: Session, assignment: UserQuotaPlanAssignment, plan: QuotaPlan, now: datetime | None = None) -> bool:
    current = now or utcnow()
    next_refresh = _ensure_aware(assignment.next_refresh_at)
    if assignment.period_start_at and next_refresh and current < next_refresh:
        return False
    start_at, end_at = period_bounds(plan.period_type, current)
    amount = plan_quota_amount(plan, assignment)
    assignment.remaining_quota = amount
    assignment.reserved_quota = min(max(int(assignment.reserved_quota or 0), 0), amount)
    assignment.period_start_at = start_at
    assignment.period_end_at = end_at
    assignment.next_refresh_at = end_at
    assignment.last_refreshed_at = current
    db.add(assignment)
    db.add(PackageQuotaLedger(
        assignment_id=assignment.id,
        plan_id=assignment.plan_id,
        user_id=assignment.user_id,
        change_amount=amount,
        action="package_period_refresh",
        note="套餐周期刷新",
        period_start_at=start_at,
    ))
    return True


def refresh_user_packages(db: Session, user_id: int) -> int:
    rows = (
        db.query(UserQuotaPlanAssignment, QuotaPlan)
        .join(QuotaPlan, QuotaPlan.id == UserQuotaPlanAssignment.plan_id)
        .filter(UserQuotaPlanAssignment.user_id == user_id, UserQuotaPlanAssignment.status == "active", QuotaPlan.status == "active")
        .with_for_update(of=UserQuotaPlanAssignment)
        .all()
    )
    changed = 0
    now = utcnow()
    for assignment, plan in rows:
        if refresh_assignment_if_due(db, assignment, plan, now):
            changed += 1
    return changed


def refresh_due_packages(db: Session, limit: int = 100) -> int:
    now = utcnow()
    rows = (
        db.query(UserQuotaPlanAssignment, QuotaPlan)
        .join(QuotaPlan, QuotaPlan.id == UserQuotaPlanAssignment.plan_id)
        .filter(UserQuotaPlanAssignment.status == "active", QuotaPlan.status == "active")
        .filter((UserQuotaPlanAssignment.next_refresh_at.is_(None)) | (UserQuotaPlanAssignment.next_refresh_at <= now))
        .order_by(UserQuotaPlanAssignment.next_refresh_at.asc().nullsfirst(), UserQuotaPlanAssignment.id.asc())
        .limit(limit)
        .with_for_update(of=UserQuotaPlanAssignment)
        .all()
    )
    changed = 0
    for assignment, plan in rows:
        if refresh_assignment_if_due(db, assignment, plan, now):
            changed += 1
    return changed


def bind_plan_to_user(db: Session, user: User, plan: QuotaPlan, operator_user_id: int | None = None) -> UserQuotaPlanAssignment:
    existing = db.query(UserQuotaPlanAssignment).filter(UserQuotaPlanAssignment.user_id == user.id, UserQuotaPlanAssignment.plan_id == plan.id, UserQuotaPlanAssignment.status == "active").first()
    if existing:
        return existing
    start_at, end_at = period_bounds(plan.period_type)
    amount = plan_quota_amount(plan)
    row = UserQuotaPlanAssignment(
        user_id=user.id,
        plan_id=plan.id,
        remaining_quota=amount,
        reserved_quota=0,
        period_start_at=start_at,
        period_end_at=end_at,
        next_refresh_at=end_at,
        last_refreshed_at=utcnow(),
        status="active",
    )
    db.add(row)
    db.flush()
    db.add(PackageQuotaLedger(assignment_id=row.id, plan_id=plan.id, user_id=user.id, change_amount=amount, action="package_bind", note="绑定套餐", period_start_at=start_at, operator_user_id=operator_user_id))
    return row


def update_assignment_custom_quota(db: Session, assignment: UserQuotaPlanAssignment, plan: QuotaPlan, value: int | None, operator_user_id: int | None = None) -> None:
    old_amount = plan_quota_amount(plan, assignment)
    assignment.custom_quota_amount = value if value is not None and int(value) >= 0 else None
    new_amount = plan_quota_amount(plan, assignment)
    delta = new_amount - old_amount
    if delta > 0:
        assignment.remaining_quota = int(assignment.remaining_quota or 0) + delta
    elif delta < 0:
        assignment.remaining_quota = max(int(assignment.remaining_quota or 0) + delta, 0)
    db.add(assignment)
    db.add(PackageQuotaLedger(assignment_id=assignment.id, plan_id=assignment.plan_id, user_id=assignment.user_id, change_amount=delta, action="package_custom_quota_update", note=f"定制额度调整为 {new_amount}", period_start_at=assignment.period_start_at, operator_user_id=operator_user_id))


def deactivate_plan_assignments(db: Session, plan_id: int, operator_user_id: int | None = None) -> int:
    rows = db.query(UserQuotaPlanAssignment).filter(UserQuotaPlanAssignment.plan_id == plan_id, UserQuotaPlanAssignment.status == "active").all()
    count = 0
    for row in rows:
        row.status = "disabled"
        db.add(row)
        db.add(PackageQuotaLedger(assignment_id=row.id, plan_id=row.plan_id, user_id=row.user_id, change_amount=0, action="package_unbind_by_plan_disabled", note="套餐停用自动解绑", period_start_at=row.period_start_at, operator_user_id=operator_user_id))
        count += 1
    return count


def _get_wallet(db: Session, user_id: int) -> QuotaWallet:
    wallet = db.query(QuotaWallet).filter(QuotaWallet.user_id == user_id).with_for_update().first()
    if not wallet:
        wallet = QuotaWallet(user_id=user_id, remaining_quota=0, total_granted=0, total_used=0, reserved_quota=0)
        db.add(wallet)
        db.flush()
    return wallet


def reserve_quota_for_job(db: Session, job: Job) -> JobQuotaReservation:
    refresh_user_packages(db, int(job.user_id))
    rows = (
        db.query(UserQuotaPlanAssignment)
        .join(QuotaPlan, QuotaPlan.id == UserQuotaPlanAssignment.plan_id)
        .filter(UserQuotaPlanAssignment.user_id == job.user_id, UserQuotaPlanAssignment.status == "active", QuotaPlan.status == "active")
        .with_for_update(of=UserQuotaPlanAssignment)
        .all()
    )
    available = [row for row in rows if int(row.remaining_quota or 0) - int(row.reserved_quota or 0) > 0]
    if available:
        assignment = random.choice(available)
        assignment.reserved_quota = int(assignment.reserved_quota or 0) + 1
        db.add(assignment)
        reservation = JobQuotaReservation(job_id=job.id, user_id=job.user_id, source_type="package", assignment_id=assignment.id, amount=1, status="reserved")
        db.add(reservation)
        return reservation

    wallet = _get_wallet(db, int(job.user_id))
    if int(wallet.remaining_quota or 0) - int(wallet.reserved_quota or 0) <= 0:
        raise ValueError("额度不足")
    wallet.reserved_quota = int(wallet.reserved_quota or 0) + 1
    db.add(wallet)
    reservation = JobQuotaReservation(job_id=job.id, user_id=job.user_id, source_type="personal", amount=1, status="reserved")
    db.add(reservation)
    return reservation


def charge_reserved_quota(db: Session, job: Job) -> None:
    reservation = db.query(JobQuotaReservation).filter(JobQuotaReservation.job_id == job.id).with_for_update().first()
    if reservation and reservation.status == "charged":
        return
    if not reservation:
        wallet = _get_wallet(db, int(job.user_id))
        if int(wallet.reserved_quota or 0) > 0:
            wallet.reserved_quota = int(wallet.reserved_quota or 0) - 1
        wallet.remaining_quota = int(wallet.remaining_quota or 0) - 1
        wallet.total_used = int(wallet.total_used or 0) + 1
        db.add(wallet)
        db.add(QuotaLedger(user_id=job.user_id, job_id=job.id, change_amount=-1, action="debit_create_success", note="Video generation submitted.", operator_user_id=job.user_id))
        return
    if reservation.status != "reserved":
        raise ValueError("任务额度预占状态异常")
    if reservation.source_type == "package" and reservation.assignment_id:
        assignment = db.query(UserQuotaPlanAssignment).filter(UserQuotaPlanAssignment.id == reservation.assignment_id).with_for_update().first()
        if not assignment:
            raise ValueError("套餐绑定不存在")
        assignment.reserved_quota = max(int(assignment.reserved_quota or 0) - int(reservation.amount or 1), 0)
        assignment.remaining_quota = max(int(assignment.remaining_quota or 0) - int(reservation.amount or 1), 0)
        db.add(assignment)
        db.add(PackageQuotaLedger(assignment_id=assignment.id, plan_id=assignment.plan_id, user_id=job.user_id, job_id=job.id, change_amount=-int(reservation.amount or 1), action=PACKAGE_CHARGE_ACTION, note="Video generation submitted.", period_start_at=assignment.period_start_at, operator_user_id=job.user_id))
    else:
        wallet = _get_wallet(db, int(job.user_id))
        wallet.reserved_quota = max(int(wallet.reserved_quota or 0) - int(reservation.amount or 1), 0)
        wallet.remaining_quota = int(wallet.remaining_quota or 0) - int(reservation.amount or 1)
        wallet.total_used = int(wallet.total_used or 0) + int(reservation.amount or 1)
        db.add(wallet)
        db.add(QuotaLedger(user_id=job.user_id, job_id=job.id, change_amount=-int(reservation.amount or 1), action="debit_create_success", note="Video generation submitted.", operator_user_id=job.user_id))
    reservation.status = "charged"
    db.add(reservation)


def release_reserved_quota_for_job(db: Session, job: Job) -> bool:
    reservation = db.query(JobQuotaReservation).filter(JobQuotaReservation.job_id == job.id).with_for_update().first()
    if not reservation or reservation.status != "reserved":
        return False
    amount = int(reservation.amount or 1)
    if reservation.source_type == "package" and reservation.assignment_id:
        assignment = db.query(UserQuotaPlanAssignment).filter(UserQuotaPlanAssignment.id == reservation.assignment_id).with_for_update().first()
        if assignment:
            assignment.reserved_quota = max(int(assignment.reserved_quota or 0) - amount, 0)
            db.add(assignment)
    else:
        wallet = _get_wallet(db, int(job.user_id))
        wallet.reserved_quota = max(int(wallet.reserved_quota or 0) - amount, 0)
        db.add(wallet)
    reservation.status = "released"
    db.add(reservation)
    return True


def refund_charged_quota_for_job(db: Session, job: Job, reason: str | None = None) -> bool:
    reservation = db.query(JobQuotaReservation).filter(JobQuotaReservation.job_id == job.id).with_for_update().first()
    if not reservation or reservation.status != "charged":
        return False
    amount = int(reservation.amount or 1)
    if reservation.source_type == "package" and reservation.assignment_id:
        already = db.query(PackageQuotaLedger.id).filter(PackageQuotaLedger.job_id == job.id, PackageQuotaLedger.action == PACKAGE_REFUND_ACTION).first()
        if already:
            reservation.status = "refunded"
            db.add(reservation)
            return False
        assignment = db.query(UserQuotaPlanAssignment).filter(UserQuotaPlanAssignment.id == reservation.assignment_id).with_for_update().first()
        if assignment:
            assignment.remaining_quota = int(assignment.remaining_quota or 0) + amount
            db.add(assignment)
            db.add(PackageQuotaLedger(assignment_id=assignment.id, plan_id=assignment.plan_id, user_id=job.user_id, job_id=job.id, change_amount=amount, action=PACKAGE_REFUND_ACTION, note=(reason or "Failed job quota refunded.")[:1000], period_start_at=assignment.period_start_at, operator_user_id=job.user_id))
        reservation.status = "refunded"
        db.add(reservation)
        add_event(db, job.id, "info", "quota_refunded", reason or "Failed job quota refunded.")
        return True
    return False
