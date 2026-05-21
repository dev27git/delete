from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .database import SessionLocal
from .models import CapabilityAssessment


def mark_stale_assessments(max_age_days: int = 30) -> int:
    threshold = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    updated_count = 0
    with SessionLocal() as db:
        assessments = db.scalars(select(CapabilityAssessment)).all()
        for assessment in assessments:
            stale_by_review = assessment.last_reviewed_at is None or assessment.last_reviewed_at < threshold
            stale_by_source = (
                assessment.source_last_checked_at is None
                or assessment.source_last_checked_at < threshold
            )
            should_flag = stale_by_review or stale_by_source
            if assessment.needs_review != should_flag:
                assessment.needs_review = should_flag
                updated_count += 1
        db.commit()
    return updated_count


if __name__ == "__main__":
    count = mark_stale_assessments(max_age_days=30)
    print(f"Marked {count} assessment(s) as review-needed.")
