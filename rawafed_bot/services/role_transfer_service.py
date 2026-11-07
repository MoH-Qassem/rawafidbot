"""Unique official roles and CEO-approved transfer requests."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from rawafed_bot.core.config import settings
from rawafed_bot.database.models.audit_log import AuditLog
from rawafed_bot.database.models.member import Member
from rawafed_bot.database.models.role import MemberRole, Permission, Role, RolePermission
from rawafed_bot.database.models.role_transfer import RoleTransferRequest
from rawafed_bot.services.permission_service import PermissionErrorDenied, PermissionService

# Map onboarding title codes → official role codes (None = display-only)
TITLE_TO_ROLE = {
    "ceo_title": "ceo",
    "finance": "finance_manager",
    "accountant": "accountant",
    "ops": "ops_manager",
    "board": "board_member",
    "staff": "staff",
    "other": None,
}


class RoleTransferService:
    @staticmethod
    def ensure_extra_roles(db: Session) -> None:
        PermissionService.seed_catalog(db)
        extras = [
            ("ops_manager", "مدير عمليات", True, True),
            ("staff", "موظف", False, False),
        ]
        existing = {r.code for r in db.query(Role).all()}
        for code, name_ar, is_system, is_unique in extras:
            if code not in existing:
                db.add(Role(
                    code=code,
                    name_ar=name_ar,
                    is_system=is_system,
                    is_active=True,
                    is_unique=is_unique,
                ))
        for code, unique in (
            ("ceo", True),
            ("finance_manager", True),
            ("accountant", True),
            ("board_member", False),
        ):
            role = db.query(Role).filter_by(code=code).first()
            if role:
                role.is_unique = unique
                db.add(role)
        # ops_manager / staff must have usable defaults (otherwise menu buttons look dead)
        from rawafed_bot.services.permissions_catalog import MEMBER_DEFAULT_PERMISSIONS
        perms = {p.code: p for p in db.query(Permission).all()}
        for role_code in ("ops_manager", "staff"):
            role = db.query(Role).filter_by(code=role_code).first()
            if not role:
                continue
            for pcode in MEMBER_DEFAULT_PERMISSIONS:
                perm = perms.get(pcode)
                if not perm:
                    continue
                row = db.query(RolePermission).filter_by(
                    role_id=role.id, permission_id=perm.id
                ).first()
                if not row:
                    db.add(RolePermission(
                        role_id=role.id, permission_id=perm.id, is_granted=True
                    ))
                elif not row.is_granted:
                    row.is_granted = True
                    db.add(row)
        db.commit()

    @staticmethod
    def holder_of(db: Session, role_id: int) -> Optional[Member]:
        holders = RoleTransferService.holders(db, role_id)
        return holders[0] if holders else None

    @staticmethod
    def holders(db: Session, role_id: int) -> list:
        links = db.query(MemberRole).filter_by(role_id=role_id).all()
        out = []
        for link in links:
            m = db.query(Member).filter_by(id=link.member_id, is_active=True).first()
            if m:
                out.append(m)
        return out

    @staticmethod
    def maybe_request_on_title(
        db: Session, member: Member, title_code: str, bot_notify: bool = False
    ) -> Optional[str]:
        """If title maps to a unique occupied role, open a transfer request (not auto-assign)."""
        RoleTransferService.ensure_extra_roles(db)
        role_code = TITLE_TO_ROLE.get(title_code)
        if not role_code or role_code == "ceo":
            # Never auto-claim CEO via title
            if role_code == "ceo":
                return (
                    "منصب CEO محمي. اختيار المسمى التعريفي لا يمنحك صلاحيات CEO. "
                    "نقل المنصب يتم فقط بموافقة CEO الحالي."
                )
            return None
        role = db.query(Role).filter_by(code=role_code, is_active=True).first()
        if not role:
            return None
        if not role.is_unique:
            # Multi-holder: assign if empty role link
            existing = db.query(MemberRole).filter_by(member_id=member.id).first()
            if not existing:
                db.add(MemberRole(member_id=member.id, role_id=role.id))
                db.commit()
            return None

        holders = RoleTransferService.holders(db, role.id)
        if not holders:
            # Free unique role — assign officially
            link = db.query(MemberRole).filter_by(member_id=member.id).first()
            if link:
                link.role_id = role.id
                db.add(link)
            else:
                db.add(MemberRole(member_id=member.id, role_id=role.id))
            db.add(AuditLog(
                action="assign_role",
                entity_type="member_role",
                entity_id=member.id,
                member_id=member.id,
                new_values=f"auto_free_unique code={role.code}",
            ))
            db.commit()
            return f"تم تعيين المنصب الرسمي «{role.name_ar}» لك (كان شاغراً)."

        holder = holders[0]
        if holder.id == member.id:
            return None
        # Create pending transfer request
        pending = (
            db.query(RoleTransferRequest)
            .filter_by(role_id=role.id, requester_id=member.id, status="pending")
            .first()
        )
        if pending:
            return f"لديك طلب معلّق لنقل منصب «{role.name_ar}»."
        req = RoleTransferRequest(
            role_id=role.id,
            requester_id=member.id,
            current_holder_id=holder.id,
            status="pending",
            created_at=datetime.utcnow(),
        )
        db.add(req)
        db.add(AuditLog(
            action="role_transfer_request",
            entity_type="role_transfer",
            entity_id=0,
            member_id=member.id,
            new_values=f"role={role.code}, holder={holder.id}",
        ))
        db.commit()
        return (
            f"هذا المنصب مشغول حالياً بواسطة {holder.get_display_name()}.\n"
            f"تم إرسال طلب للـ CEO لنقل منصب «{role.name_ar}» إليك."
        )

    @staticmethod
    def approve(db: Session, request_id: int, ceo: Member) -> RoleTransferRequest:
        if not ceo.is_ceo and ceo.telegram_id != settings.CEO_TELEGRAM_ID:
            raise PermissionErrorDenied("موافقة نقل المناصب للـ CEO فقط.")
        req = db.query(RoleTransferRequest).filter_by(id=request_id, status="pending").first()
        if not req:
            raise PermissionErrorDenied("الطلب غير موجود أو غير معلّق.")
        role = db.query(Role).filter_by(id=req.role_id).first()
        if not role:
            raise PermissionErrorDenied("المنصب غير موجود.")
        if role.code == "ceo":
            raise PermissionErrorDenied("نقل CEO يتم عبر عملية نقل صريحة منفصلة.")

        # Atomic: remove role from all holders, assign to requester
        for link in db.query(MemberRole).filter_by(role_id=role.id).all():
            # Reassign previous holders to board_member
            board = db.query(Role).filter_by(code="board_member").first()
            if board and link.member_id != req.requester_id:
                link.role_id = board.id
                db.add(link)
            elif link.member_id != req.requester_id:
                db.delete(link)

        requester_link = db.query(MemberRole).filter_by(member_id=req.requester_id).first()
        if requester_link:
            requester_link.role_id = role.id
            requester_link.assigned_by = ceo.id
            db.add(requester_link)
        else:
            db.add(MemberRole(
                member_id=req.requester_id, role_id=role.id, assigned_by=ceo.id
            ))

        req.status = "approved"
        req.resolved_by = ceo.id
        req.resolved_at = datetime.utcnow()
        db.add(req)
        db.add(AuditLog(
            action="role_transfer_approve",
            entity_type="role_transfer",
            entity_id=req.id,
            member_id=ceo.id,
            new_values=f"role={role.code}, to={req.requester_id}",
        ))
        db.commit()
        db.refresh(req)
        return req

    @staticmethod
    def reject(db: Session, request_id: int, ceo: Member) -> RoleTransferRequest:
        if not ceo.is_ceo and ceo.telegram_id != settings.CEO_TELEGRAM_ID:
            raise PermissionErrorDenied("رفض الطلبات للـ CEO فقط.")
        req = db.query(RoleTransferRequest).filter_by(id=request_id, status="pending").first()
        if not req:
            raise PermissionErrorDenied("الطلب غير موجود.")
        req.status = "rejected"
        req.resolved_by = ceo.id
        req.resolved_at = datetime.utcnow()
        db.add(req)
        db.add(AuditLog(
            action="role_transfer_reject",
            entity_type="role_transfer",
            entity_id=req.id,
            member_id=ceo.id,
        ))
        db.commit()
        db.refresh(req)
        return req
