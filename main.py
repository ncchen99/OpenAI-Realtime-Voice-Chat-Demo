from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import asyncio
import json
import base64
import os
import websockets
from dotenv import load_dotenv
import logging

# 載入環境變數
load_dotenv()

# 設定日誌
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="OpenAI Realtime Voice Chat API", version="1.0.0")

# 掛載靜態檔案
app.mount("/static", StaticFiles(directory="static"), name="static")

# OpenAI Realtime API 設定
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
REALTIME_API_URL = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01"

@app.get("/")
async def get():
    """提供主頁面"""
    return FileResponse('static/index.html')

@app.websocket("/realtime-voice")
async def websocket_realtime_voice(websocket: WebSocket):
    """處理 OpenAI Realtime API 連接的 WebSocket 中繼"""
    await websocket.accept()
    logger.info("客戶端連接到 Realtime Voice WebSocket")
    
    openai_ws = None
    
    try:
        # 建立到 OpenAI Realtime API 的 WebSocket 連接
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "OpenAI-Beta": "realtime=v1"
        }
        
        openai_ws = await websockets.connect(REALTIME_API_URL, extra_headers=headers)
        logger.info("已連接到 OpenAI Realtime API")
        
        # 初始化會話設定
        session_config = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "instructions": "你是一個友善且充滿活力的AI助手。請務必用繁體中文進行對話，語調自然流暢。請快速且簡潔地回應，避免過長的回答。",
                "voice": "alloy",  
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {
                    "model": "whisper-1",
                    "language": "zh"  # 指定中文語言
                },
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.6,          # 提高靈敏度
                    "prefix_padding_ms": 200,   # 減少前置延遲
                    "silence_duration_ms": 150  # 減少靜音檢測時間
                },
                "temperature": 0.7,  # 稍微降低溫度以提高響應速度
                "max_response_output_tokens": 2048,  # 限制回應長度以加快速度
                "tools": [],
                "tool_choice": "none"
            }
        }
        
        await openai_ws.send(json.dumps(session_config))
        logger.info("已發送會話配置")
        
        # 建立雙向資料轉發
        async def forward_from_client():
            """從客戶端轉發訊息到 OpenAI"""
            try:
                async for message in websocket.iter_text():
                    data = json.loads(message)
                    logger.debug(f"客戶端 -> OpenAI: {data.get('type', 'unknown')}")
                    await openai_ws.send(message)
            except WebSocketDisconnect:
                logger.info("客戶端斷開連接")
            except Exception as e:
                logger.error(f"客戶端轉發錯誤: {e}")
        
        async def forward_from_openai():
            """從 OpenAI 轉發訊息到客戶端"""
            try:
                async for message in openai_ws:
                    data = json.loads(message)
                    event_type = data.get('type', 'unknown')
                    logger.debug(f"OpenAI -> 客戶端: {event_type}")
                    
                    # 處理特定事件類型
                    if event_type == "session.created":
                        logger.info("OpenAI 會話已建立")
                    elif event_type == "error":
                        logger.error(f"OpenAI API 錯誤: {data.get('error', {})}")
                    
                    await websocket.send_text(message)
            except websockets.exceptions.ConnectionClosedError:
                logger.info("OpenAI WebSocket 連接已關閉")
            except Exception as e:
                logger.error(f"OpenAI 轉發錯誤: {e}")
        
        # 同時執行雙向轉發
        await asyncio.gather(
            forward_from_client(),
            forward_from_openai(),
            return_exceptions=True
        )
        
    except websockets.exceptions.InvalidStatusCode as e:
        error_msg = f"OpenAI API 連接失敗: HTTP {e.status_code}"
        logger.error(error_msg)
        await websocket.send_text(json.dumps({
            "type": "error",
            "error": {"message": error_msg}
        }))
    except Exception as e:
        error_msg = f"Realtime API 連接錯誤: {str(e)}"
        logger.error(error_msg)
        await websocket.send_text(json.dumps({
            "type": "error", 
            "error": {"message": error_msg}
        }))
    finally:
        # 清理連接
        if openai_ws:
            await openai_ws.close()
        logger.info("WebSocket 連接已清理")

@app.websocket("/text-chat")
async def websocket_text_chat(websocket: WebSocket):
    """處理純文字聊天的 WebSocket 連接"""
    await websocket.accept()
    logger.info("客戶端連接到文字聊天 WebSocket")
    
    openai_ws = None
    
    try:
        # 建立到 OpenAI Realtime API 的 WebSocket 連接
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "OpenAI-Beta": "realtime=v1"
        }
        
        openai_ws = await websockets.connect(REALTIME_API_URL, extra_headers=headers)
        logger.info("文字模式已連接到 OpenAI Realtime API")
        
        # 初始化文字專用會話設定
        session_config = {
            "type": "session.update",
            "session": {
                "modalities": ["text"],  # 只使用文字模式
                "instructions": "你是一個友善且充滿活力的AI助手。請務必用繁體中文進行對話。你可以使用 Markdown 格式來美化回應內容，包括標題、列表、程式碼區塊等。回應要詳細且有用。",
                "temperature": 0.8,
                "max_response_output_tokens": 4096,
                "tools": [],
                "tool_choice": "none"
            }
        }
        
        await openai_ws.send(json.dumps(session_config))
        logger.info("已發送文字模式會話配置")
        
        # 建立雙向資料轉發
        async def forward_from_client():
            """從客戶端轉發訊息到 OpenAI"""
            try:
                async for message in websocket.iter_text():
                    data = json.loads(message)
                    logger.debug(f"文字模式客戶端 -> OpenAI: {data.get('type', 'unknown')}")
                    await openai_ws.send(message)
            except WebSocketDisconnect:
                logger.info("文字模式客戶端斷開連接")
            except Exception as e:
                logger.error(f"文字模式客戶端轉發錯誤: {e}")
        
        async def forward_from_openai():
            """從 OpenAI 轉發訊息到客戶端"""
            try:
                async for message in openai_ws:
                    data = json.loads(message)
                    event_type = data.get('type', 'unknown')
                    logger.debug(f"文字模式 OpenAI -> 客戶端: {event_type}")
                    
                    # 處理特定事件類型
                    if event_type == "session.created":
                        logger.info("文字模式 OpenAI 會話已建立")
                    elif event_type == "error":
                        logger.error(f"文字模式 OpenAI API 錯誤: {data.get('error', {})}")
                    
                    await websocket.send_text(message)
            except websockets.exceptions.ConnectionClosedError:
                logger.info("文字模式 OpenAI WebSocket 連接已關閉")
            except Exception as e:
                logger.error(f"文字模式 OpenAI 轉發錯誤: {e}")
        
        # 同時執行雙向轉發
        await asyncio.gather(
            forward_from_client(),
            forward_from_openai(),
            return_exceptions=True
        )
        
    except websockets.exceptions.InvalidStatusCode as e:
        error_msg = f"文字模式 OpenAI API 連接失敗: HTTP {e.status_code}"
        logger.error(error_msg)
        await websocket.send_text(json.dumps({
            "type": "error",
            "error": {"message": error_msg}
        }))
    except Exception as e:
        error_msg = f"文字模式 Realtime API 連接錯誤: {str(e)}"
        logger.error(error_msg)
        await websocket.send_text(json.dumps({
            "type": "error", 
            "error": {"message": error_msg}
        }))
    finally:
        # 清理連接
        if openai_ws:
            await openai_ws.close()
        logger.info("文字模式 WebSocket 連接已清理")

@app.get("/health")
async def health_check():
    """健康檢查端點"""
    return {"status": "healthy", "message": "OpenAI Realtime Chat API 正常運行"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 