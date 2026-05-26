"""API endpoints for Telegram bot management."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel

from gst_automation.telegram_bot.service import TelegramUserService, TelegramAuditService
from gst_automation.telegram_bot import TelegramUserInfo

router = APIRouter(prefix="/telegram", tags=["telegram"])


class TelegramUserRegisterRequest(BaseModel):
    """Request to register a Telegram user."""

    telegram_user_id: int
    telegram_chat_id: int
    telegram_username: str | None = None
    telegram_first_name: str | None = None
    telegram_last_name: str | None = None
    role: str = "operator"


class TelegramUserResponse(BaseModel):
    """Response with user info."""

    id: str
    telegram_user_id: int
    telegram_chat_id: int
    telegram_username: str | None
    status: str
    role: str


class TelegramStatusResponse(BaseModel):
    """Response with Telegram bot status."""

    operators_count: int
    active_operators: int


@router.post("/operators/register", response_model=TelegramUserResponse)
async def register_operator(request: Request, req: TelegramUserRegisterRequest) -> dict:
    """Register a new Telegram operator.
    
    Requires admin authorization (future).
    """
    db = request.app.state.db

    async with db.session() as session:
        service = TelegramUserService(session)

        # Check if user already exists
        existing = await service.get_user(telegram_user_id=req.telegram_user_id)
        if existing and existing.status == "active":
            raise HTTPException(status_code=409, detail="User already registered")

        # Register user
        user = await service.register_user(
            telegram_user_id=req.telegram_user_id,
            telegram_chat_id=req.telegram_chat_id,
            telegram_username=req.telegram_username,
            telegram_first_name=req.telegram_first_name,
            telegram_last_name=req.telegram_last_name,
            role=req.role,
        )

        # Audit log
        audit_service = TelegramAuditService(session)
        await audit_service.log_action(
            telegram_user_id=req.telegram_user_id,
            action="user_registered",
            details={
                "username": req.telegram_username,
                "role": req.role,
            },
        )

        await session.commit()

        return {
            "id": str(user.id),
            "telegram_user_id": user.telegram_user_id,
            "telegram_chat_id": user.telegram_chat_id,
            "telegram_username": user.telegram_username,
            "status": user.status,
            "role": user.role,
        }


@router.get("/operators/{telegram_user_id}", response_model=TelegramUserResponse)
async def get_operator(request: Request, telegram_user_id: int) -> dict:
    """Get operator info by Telegram user ID."""
    db = request.app.state.db

    async with db.session() as session:
        service = TelegramUserService(session)
        user = await service.get_user(telegram_user_id=telegram_user_id)

        if not user:
            raise HTTPException(status_code=404, detail="Operator not found")

        return {
            "id": str(user.id),
            "telegram_user_id": user.telegram_user_id,
            "telegram_chat_id": user.telegram_chat_id,
            "telegram_username": user.telegram_username,
            "status": user.status,
            "role": user.role,
        }


@router.post("/operators/{telegram_user_id}/disable")
async def disable_operator(request: Request, telegram_user_id: int) -> dict:
    """Disable an operator."""
    db = request.app.state.db

    async with db.session() as session:
        service = TelegramUserService(session)
        success = await service.disable_user(telegram_user_id=telegram_user_id)

        if not success:
            raise HTTPException(status_code=404, detail="Operator not found")

        # Audit log
        audit_service = TelegramAuditService(session)
        await audit_service.log_action(
            telegram_user_id=telegram_user_id,
            action="user_disabled",
        )

        await session.commit()

        return {"status": "disabled", "telegram_user_id": telegram_user_id}


@router.get("/status", response_model=TelegramStatusResponse)
async def get_telegram_status(request: Request) -> dict:
    """Get Telegram bot status."""
    db = request.app.state.db

    async with db.session() as session:
        service = TelegramUserService(session)
        operators = await service.list_operators()

        return {
            "operators_count": len(operators),
            "active_operators": len([op for op in operators if op.status == "active"]),
        }


@router.get("/operators/audit/{telegram_user_id}")
async def get_operator_audit(request: Request, telegram_user_id: int, limit: int = 50) -> dict:
    """Get audit log for an operator."""
    db = request.app.state.db

    async with db.session() as session:
        audit_service = TelegramAuditService(session)
        actions = await audit_service.get_user_actions(
            telegram_user_id=telegram_user_id,
            limit=limit,
        )

        return {
            "telegram_user_id": telegram_user_id,
            "actions": [
                {
                    "id": str(a.id),
                    "action": a.action,
                    "details": a.details_json,
                    "created_at": a.created_at.isoformat(),
                }
                for a in actions
            ],
        }
