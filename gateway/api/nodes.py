from fastapi import Body
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
    nodes = gateway.get_all_node_status()
    backups = gateway.get_nodes_backups()
    res = []

    for id, status in nodes.items():
        res.append({
            "id": id,
            "status": status,
            "backup": backups.get(id)
        })

    return res

@router.get("/{node_id}/snapshots")
async def get_node_snapshots(
    node_id: str,
    current_user: Annotated[schemas.User, Depends(security.get_current_user)],
):
    return gateway.get_node_snapshots(node_id)

@router.post("/{node_id}/recover")
async def recover_node(
    node_id: str,
    body: Annotated[schemas.NodeRecover, Body()],
    current_user: Annotated[schemas.User, Depends(security.get_current_user)],
):
    return gateway.recover_node(node_id, body.snapshot_id)
