"""
WebSocket connection manager.
Broadcasts events to all connected dashboard clients.
"""
import json
import logging
from typing import List
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.alert_connections: List[WebSocket] = []
        self.transaction_connections: List[WebSocket] = []

    async def connect_alerts(self, ws: WebSocket):
        await ws.accept()
        self.alert_connections.append(ws)

    async def connect_transactions(self, ws: WebSocket):
        await ws.accept()
        self.transaction_connections.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.alert_connections:
            self.alert_connections.remove(ws)
        if ws in self.transaction_connections:
            self.transaction_connections.remove(ws)

    async def broadcast_alert(self, data: dict):
        payload = json.dumps(data)
        dead = []
        for ws in self.alert_connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def broadcast_transaction(self, data: dict):
        payload = json.dumps(data)
        dead = []
        for ws in self.transaction_connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()
