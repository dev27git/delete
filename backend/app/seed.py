from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Company, CompanyTypeEnum, Feature


DEFAULT_COMPETITORS = [
    ("Netskope", "SSE", "https://www.netskope.com"),
    ("Varonis", "DSPM", "https://www.varonis.com"),
    ("Microsoft Purview", "Data Security", "https://www.microsoft.com"),
]

DEFAULT_FEATURES = [
    ("Data Discovery Coverage", "Discovery", 1.3),
    ("Risk Prioritization", "Analytics", 1.2),
    ("Sensitive Data Policy Automation", "Governance", 1.4),
    ("Cloud SaaS Visibility", "Visibility", 1.0),
]


def seed_defaults(db: Session) -> None:
    concentric_exists = db.scalar(select(Company).where(Company.company_type == CompanyTypeEnum.concentric))
    if not concentric_exists:
        db.add(
            Company(
                name="Concentric AI",
                company_type=CompanyTypeEnum.concentric,
                segment="DSPM",
                website="https://www.concentric.ai",
                description="Internal baseline company profile for competitive scoring.",
                is_seed=True,
                created_by="system",
            )
        )

    for name, segment, website in DEFAULT_COMPETITORS:
        exists = db.scalar(select(Company).where(Company.name == name))
        if not exists:
            db.add(
                Company(
                    name=name,
                    company_type=CompanyTypeEnum.competitor,
                    segment=segment,
                    website=website,
                    is_seed=True,
                    created_by="system",
                )
            )

    for name, category, weight in DEFAULT_FEATURES:
        exists = db.scalar(select(Feature).where(Feature.name == name))
        if not exists:
            db.add(
                Feature(
                    name=name,
                    category=category,
                    importance_weight=weight,
                    created_by="system",
                )
            )

    db.commit()
