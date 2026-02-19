from typing import Annotated, List
from fastapi import Depends
from sqlalchemy.orm import Session
from fastapi import APIRouter

from ..lib import models, schemas, security
from ..lib.db import get_db


router = APIRouter(prefix="/users", tags=["users"])


@router.get("/", response_model=List[schemas.User])
def read_users(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    users = db.query(models.User).offset(skip).limit(limit).all()
    return users


@router.get("/me", response_model=schemas.User)
async def get_me(
    current_user: Annotated[schemas.User, Depends(security.get_current_user)],
):
    return current_user
