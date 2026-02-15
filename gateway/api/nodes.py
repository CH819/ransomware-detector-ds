from typing import Annotated
from fastapi import Depends
from fastapi import APIRouter

from ..lib import schemas, security
from ..lib.gateway import gateway

router = APIRouter(prefix="/nodes", tags=["nodes"])


@router.get("/")
async def get_nodes(
    current_user: Annotated[schemas.User, Depends(security.get_current_user)],
):
    return gateway.get_node_status()
