from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.core.logging import get_logger
from gst_automation.core.settings import Settings
from gst_automation.db.models.email.delivery import EmailDelivery
from gst_automation.email.smtp_mailer import SmtpMailer
from gst_automation.orchestration.handlers.base import JobHandlerV2
from gst_automation.orchestration.handlers.context import JobRunContext
from gst_automation.archive.hashing import sha256_file


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class EmailDeliveryJobHandler(JobHandlerV2):
    async def run_with_context(self, *, job_id: uuid.UUID, payload_json: str, ctx: JobRunContext) -> None:
        settings: Settings = ctx.settings
        payload = json.loads(payload_json)
        client_id = uuid.UUID(payload["client_id"])
        to_email = str(payload["to_email"])
        cc_email = payload.get("cc_email")
        subject = str(payload["subject"])
        body = str(payload.get("body") or "")
        attachment_path = Path(payload["attachment_path"])
        filename = str(payload.get("filename") or attachment_path.name)
        idem = payload.get("idempotency_key")
        if not idem:
            # Default idempotency: client+attachment hash.
            idem = f"{client_id}:{sha256_file(attachment_path)}"

        # Idempotency: if already sent, treat as success; if queued/failed, reuse same row for retry.
        res = await ctx.session.execute(select(EmailDelivery).where(EmailDelivery.idempotency_key == str(idem)).limit(1))
        row = res.scalars().first()
        if row is None:
            row = EmailDelivery(
                client_id=client_id,
                to_email=to_email,
                cc_email=str(cc_email) if cc_email else None,
                subject=subject,
                attachment_path=str(attachment_path),
                idempotency_key=str(idem),
                status="queued",
            )
            ctx.session.add(row)
            await ctx.session.flush()
        elif row.status == "sent":
            logger.info("email.idempotent_skip", client_id=str(client_id), to_email=to_email, idempotency_key=str(idem))
            return
        else:
            row.to_email = to_email
            row.cc_email = str(cc_email) if cc_email else None
            row.subject = subject
            row.attachment_path = str(attachment_path)
            row.status = "queued"
            row.error = None
            await ctx.session.flush()
        try:
            await SmtpMailer(settings=settings).send_with_attachment(
                to_email=to_email,
                cc_email=str(cc_email) if cc_email else None,
                subject=subject,
                body=body,
                attachment_path=attachment_path,
                filename=filename,
            )
            row.status = "sent"
            row.sent_at = datetime.now(UTC)
            await ctx.session.flush()
            logger.info("email.sent", client_id=str(client_id), to_email=to_email)
        except Exception as exc:  # noqa: BLE001
            row.status = "failed"
            row.error = str(exc)
            await ctx.session.flush()
            logger.warning("email.failed", client_id=str(client_id), err=str(exc))
            raise
