"""Dynamic role/permission checks. CEO privileges are non-revocable."""
from __future__ import annotations

from typing import List, Optional, Set

from sqlalchemy.orm import Session

from rawafed_bot.core.config import settings
from rawafed_bot.database.models.audit_log import AuditLog
from rawafed_bot.database.models.member import Member
from rawafed_bot.database.models.role import MemberRole, Permission, Role, RolePermission
from rawafed_bot.services.permissions_catalog import (
    ALL_PERMISSIONS,
    CEO_LOCKED_PERMISSIONS,
    CEO_ONLY_PERMISSIONS,
    DEFAULT_ROLES,
    MEMBER_DEFAULT_PERMISSIONS,
)


class PermissionErrorDenied(PermissionError):
    pass


class PermissionService:
    @staticmethod
    def seed_catalog(db: Session) -> None:
        existing_perm = {p.code for p in db.query(Permission).all()}
        for code, name_ar, category in ALL_PERMISSIONS:
            if code not in existing_perm:
                db.add(Permission(code=code, name_ar=name_ar, category=category, is_active=True))
        db.flush()

        existing_roles = {r.code for r in db.query(Role).all()}
        unique_map = {
            "ceo": True,
            "finance_manager": True,
            "accountant": True,
            "board_member": False,
        }
        for code, name_ar, is_system in DEFAULT_ROLES:
            if code not in existing_roles:
                db.add(Role(
                    code=code,
                    name_ar=name_ar,
                    is_system=is_system,
                    is_active=True,
                    is_unique=unique_map.get(code, True),
                ))
        db.flush()

        perms = {p.code: p for p in db.query(Permission).all()}
        roles = {r.code: r for r in db.query(Role).all()}

        def ensure_grant(role_code: str, perm_codes: List[str], granted: bool = True):
            role = roles[role_code]
            for code in perm_codes:
                perm = perms[code]
                row = db.query(RolePermission).filter_by(
                    role_id=role.id, permission_id=perm.id
                ).first()
                if not row:
                    db.add(RolePermission(
                        role_id=role.id, permission_id=perm.id, is_granted=granted
                    ))

        # Equal operational perms for non-CEO roles
        for role_code in ("finance_manager", "accountant", "board_member"):
            ensure_grant(role_code, MEMBER_DEFAULT_PERMISSIONS, True)
            ensure_grant(role_code, CEO_ONLY_PERMISSIONS, False)

        # CEO gets everything
        ensure_grant("ceo", [c for c, _, _ in ALL_PERMISSIONS], True)
        db.commit()

    @staticmethod
    def get_member_role(db: Session, member_id: int) -> Optional[Role]:
        link = db.query(MemberRole).filter_by(member_id=member_id).first()
        if not link:
            return None
        return db.query(Role).filter_by(id=link.role_id).first()

    @staticmethod
    def assign_role(
        db: Session, member_id: int, role_id: int, assigned_by: int
    ) -> MemberRole:
        target = db.query(Member).filter_by(id=member_id).first()
        actor = db.query(Member).filter_by(id=assigned_by).first()
        role = db.query(Role).filter_by(id=role_id, is_active=True).first()
        if not target or not actor or not role:
            raise PermissionErrorDenied("بيانات غير صالحة.")
        if target.is_ceo and role.code != "ceo":
            raise PermissionErrorDenied("لا يمكن تغيير منصب الـ CEO إلى منصب أدنى.")
        if not actor.is_ceo and actor.telegram_id != settings.CEO_TELEGRAM_ID:
            raise PermissionErrorDenied("تعيين المناصب متاح للـ CEO فقط.")
        if actor.id == target.id and not actor.is_ceo:
            raise PermissionErrorDenied("لا يمكنك تعديل منصبك بنفسك.")
        if role.code == "ceo" and not actor.is_ceo:
            raise PermissionErrorDenied("تعيين منصب CEO محظور بهذه الطريقة.")

        # Unique role: only one active holder
        if getattr(role, "is_unique", True):
            for other in db.query(MemberRole).filter_by(role_id=role_id).all():
                if other.member_id == member_id:
                    continue
                board = db.query(Role).filter_by(code="board_member").first()
                if board:
                    other.role_id = board.id
                    db.add(other)
                else:
                    db.delete(other)

        link = db.query(MemberRole).filter_by(member_id=member_id).first()
        old = f"role_id={link.role_id if link else None}"
        if link:
            link.role_id = role_id
            link.assigned_by = assigned_by
            db.add(link)
        else:
            link = MemberRole(member_id=member_id, role_id=role_id, assigned_by=assigned_by)
            db.add(link)
        db.add(AuditLog(
            action="assign_role",
            entity_type="member_role",
            entity_id=member_id,
            member_id=assigned_by,
            old_values=old,
            new_values=f"role_id={role_id}, code={role.code}",
        ))
        db.commit()
        db.refresh(link)
        return link

    @staticmethod
    def member_permission_codes(db: Session, member: Member) -> Set[str]:
        if member.is_ceo or member.telegram_id == settings.CEO_TELEGRAM_ID:
            return {c for c, _, _ in ALL_PERMISSIONS}
        role = PermissionService.get_member_role(db, member.id)
        if not role:
            # Fallback equal member defaults
            return set(MEMBER_DEFAULT_PERMISSIONS)
        rows = (
            db.query(RolePermission, Permission)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .filter(
                RolePermission.role_id == role.id,
                RolePermission.is_granted == True,
                Permission.is_active == True,
            )
            .all()
        )
        return {perm.code for _, perm in rows}

    @staticmethod
    def has_permission(db: Session, member: Member, code: str) -> bool:
        if member.is_ceo or member.telegram_id == settings.CEO_TELEGRAM_ID:
            return True
        if not member.is_active:
            return False
        return code in PermissionService.member_permission_codes(db, member)

    @staticmethod
    def require(db: Session, member: Member, code: str) -> None:
        if not PermissionService.has_permission(db, member, code):
            raise PermissionErrorDenied(f"⛔ ليست لديك صلاحية: {code}")

    @staticmethod
    def set_role_permission(
        db: Session,
        role_id: int,
        permission_code: str,
        granted: bool,
        actor: Member,
    ) -> RolePermission:
        if not actor.is_ceo and actor.telegram_id != settings.CEO_TELEGRAM_ID:
            raise PermissionErrorDenied("تعديل الصلاحيات متاح للـ CEO فقط.")
        role = db.query(Role).filter_by(id=role_id).first()
        perm = db.query(Permission).filter_by(code=permission_code).first()
        if not role or not perm:
            raise PermissionErrorDenied("المنصب أو الصلاحية غير موجودة.")
        if role.code == "ceo":
            # Cannot revoke locked CEO permissions
            if permission_code in CEO_LOCKED_PERMISSIONS and not granted:
                raise PermissionErrorDenied("لا يمكن سحب صلاحيات الـ CEO الأساسية.")
        row = db.query(RolePermission).filter_by(
            role_id=role.id, permission_id=perm.id
        ).first()
        old = f"granted={row.is_granted if row else None}"
        if row:
            row.is_granted = granted
            db.add(row)
        else:
            row = RolePermission(role_id=role.id, permission_id=perm.id, is_granted=granted)
            db.add(row)
        db.add(AuditLog(
            action="set_permission",
            entity_type="role_permission",
            entity_id=role.id,
            member_id=actor.id,
            old_values=old,
            new_values=f"perm={permission_code}, granted={granted}",
        ))
        db.commit()
        db.refresh(row)
        return row

    @staticmethod
    def suggest_role_code(name_ar: str) -> str:
        """Build a stable latin-ish code from a free-form title."""
        import re
        import unicodedata

        raw = (name_ar or "").strip().lower()
        # Keep latin/digits; map spaces to _
        latin = re.sub(r"[^a-z0-9]+", "_", raw)
        latin = latin.strip("_")
        if not latin or len(latin) < 2:
            # Fallback from unicode codepoints so Arabic titles still get a code
            digest = "".join(
                f"{ord(ch):x}" for ch in unicodedata.normalize("NFKC", name_ar or "role")[:8]
            )
            latin = f"role_{digest[:12]}"
        return latin[:40]

    @staticmethod
    def create_role(db: Session, name_ar: str, code: str, actor: Member) -> Role:
        if not actor.is_ceo:
            raise PermissionErrorDenied("إنشاء المناصب متاح للـ CEO فقط.")
        name = (name_ar or "").strip()
        if not name:
            raise PermissionErrorDenied("اسم المنصب مطلوب.")
        code = (code or "").strip().lower().replace(" ", "_").replace("-", "_")
        if not code:
            code = PermissionService.suggest_role_code(name)
        # Allow only safe code chars; otherwise auto-fix
        import re
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,39}", code):
            code = PermissionService.suggest_role_code(name)
        base = code
        n = 2
        while db.query(Role).filter_by(code=code).first():
            code = f"{base}_{n}"[:40]
            n += 1
        role = Role(code=code, name_ar=name, is_system=False, is_active=True)
        db.add(role)
        db.flush()
        # Start from member defaults
        perms = {p.code: p for p in db.query(Permission).all()}
        for pcode in MEMBER_DEFAULT_PERMISSIONS:
            if pcode in perms:
                db.add(RolePermission(
                    role_id=role.id, permission_id=perms[pcode].id, is_granted=True
                ))
        for pcode in CEO_ONLY_PERMISSIONS:
            if pcode in perms:
                db.add(RolePermission(
                    role_id=role.id, permission_id=perms[pcode].id, is_granted=False
                ))
        db.add(AuditLog(
            action="create",
            entity_type="role",
            entity_id=role.id,
            member_id=actor.id,
            new_values=f"code={code}, name={name_ar}",
        ))
        db.commit()
        db.refresh(role)
        return role

    @staticmethod
    def rename_role(db: Session, role_id: int, name_ar: str, actor: Member) -> Role:
        if not actor.is_ceo:
            raise PermissionErrorDenied("تعديل المناصب متاح للـ CEO فقط.")
        role = db.query(Role).filter_by(id=role_id).first()
        if not role:
            raise PermissionErrorDenied("المنصب غير موجود.")
        old = role.name_ar
        role.name_ar = name_ar.strip()
        db.add(role)
        db.add(AuditLog(
            action="update",
            entity_type="role",
            entity_id=role.id,
            member_id=actor.id,
            old_values=old,
            new_values=name_ar,
        ))
        db.commit()
        db.refresh(role)
        return role

    @staticmethod
    def deactivate_role(db: Session, role_id: int, actor: Member) -> Role:
        if not actor.is_ceo:
            raise PermissionErrorDenied("تعطيل المناصب متاح للـ CEO فقط.")
        role = db.query(Role).filter_by(id=role_id).first()
        if not role:
            raise PermissionErrorDenied("المنصب غير موجود.")
        if role.code == "ceo" or role.is_system and role.code == "ceo":
            raise PermissionErrorDenied("لا يمكن تعطيل منصب الـ CEO.")
        if role.is_system:
            raise PermissionErrorDenied("لا يمكن حذف المناصب النظامية؛ يمكن تعطيل غير الأساسية فقط.")
        assigned = db.query(MemberRole).filter_by(role_id=role.id).count()
        if assigned:
            raise PermissionErrorDenied("المنصب معيّن لأعضاء. أعد تعيينهم أولاً.")
        role.is_active = False
        db.add(role)
        db.add(AuditLog(
            action="deactivate",
            entity_type="role",
            entity_id=role.id,
            member_id=actor.id,
            new_values=f"code={role.code}",
        ))
        db.commit()
        db.refresh(role)
        return role

    @staticmethod
    def matrix(db: Session) -> list:
        roles = db.query(Role).filter_by(is_active=True).order_by(Role.id).all()
        perms = db.query(Permission).filter_by(is_active=True).order_by(Permission.id).all()
        rows = []
        for role in roles:
            grants = {
                rp.permission_id: rp.is_granted
                for rp in db.query(RolePermission).filter_by(role_id=role.id).all()
            }
            rows.append({
                "role": role,
                "permissions": {
                    p.code: bool(grants.get(p.id, False)) for p in perms
                },
            })
        return rows
