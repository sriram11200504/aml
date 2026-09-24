from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from ..ws_manager import manager

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/alerts")
async def ws_alerts(ws: WebSocket):
    await manager.connect_alerts(ws)
    try:
        while True:
            await ws.receive_text()  # keep alive
    except WebSocketDisconnect:
        manager.disconnect(ws)


@router.websocket("/ws/transactions")
async def ws_transactions(ws: WebSocket):
    await manager.connect_transactions(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
