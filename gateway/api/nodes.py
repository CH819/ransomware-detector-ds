from fastapi import HTTPException
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
    infection_timestamps = gateway.get_nodes_infection_timestamps()
    res = []

    for id, status in nodes.items():
        res.append(
            {
                "id": id,
                "status": status,
                "backup": backups.get(id),
                "infection_timestamp": infection_timestamps.get(id),
            }
        )

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
    current_user: Annotated[schemas.User, Depends(security.get_current_user)],
):
    res = gateway.recover_node(node_id)
    if res.get("error"):
        raise HTTPException(status_code=400, detail=res["error"])

    return res
