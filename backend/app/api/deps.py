import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Case

DB = Annotated[Session, Depends(get_db)]


def current_user(x_user_id: Annotated[str, Header()] = "dev-user") -> str:
    # TODO(auth): verify the Supabase JWT from the Authorization header and return its `sub`.
    return x_user_id


User = Annotated[str, Depends(current_user)]


def get_case(case_id: uuid.UUID, db: DB, user: User) -> Case:
    case = db.get(Case, case_id)
    if case is None or case.user_id != user:
        raise HTTPException(404, "Case not found")
    return case


UserCase = Annotated[Case, Depends(get_case)]
