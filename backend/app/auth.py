from enum import Enum

from fastapi import Depends, Header, HTTPException, status


class RequestRole(str, Enum):
    analyst = "analyst"
    viewer = "viewer"


def get_role(x_role: str | None = Header(default="viewer")) -> RequestRole:
    if x_role is None:
        return RequestRole.viewer
    role = x_role.lower()
    if role not in {RequestRole.analyst.value, RequestRole.viewer.value}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="x-role must be either analyst or viewer",
        )
    return RequestRole(role)


def require_analyst(role: RequestRole = Depends(get_role)) -> RequestRole:
    if role != RequestRole.analyst:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Analyst role required for write operations",
        )
    return role
