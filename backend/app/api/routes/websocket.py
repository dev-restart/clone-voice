import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.progress import progress_events

router = APIRouter()

@router.websocket("/api/ws/progress/{progress_id}")
async def progress_websocket(websocket: WebSocket, progress_id: str):
    await websocket.accept()
    last_payload = None
    try:
        while True:
            payload = progress_events.get(progress_id, {"percent": 0, "message": "작업 대기 중입니다.", "done": False})
            if payload != last_payload:
                await websocket.send_json(payload)
                last_payload = payload.copy()
            if payload.get("done"):
                await asyncio.sleep(0.5)
                progress_events.pop(progress_id, None)
                break
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        return
