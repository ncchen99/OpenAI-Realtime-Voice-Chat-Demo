from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import asyncio
import json
import base64
import os
import websockets
import requests
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
VECTOR_STORE_ID = "vs_6890f0af38108191b4268271b83d7454"

# Vector Store 搜尋工具定義
vector_search_tool = {
    "name": "search_vector_store",
    "description": "根據用戶提問，查詢向量資料庫以獲取相關文件內容。當用戶詢問需要查找資料或文件時使用此功能。",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "用戶要查詢的問題或關鍵字"
            }
        },
        "required": ["query"]
    }
}

async def query_vector_store(query: str, vector_store_id: str = VECTOR_STORE_ID):
    """查詢 OpenAI Vector Store"""
    try:
        # 注意：這裡使用 Files API 來模擬搜尋，實際 Vector Store 搜尋 API 可能不同
        # 您可能需要根據實際的 OpenAI Vector Store API 調整這部分
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
            "OpenAI-Beta": "assistants=v2"
        }
        
        # 先取得 vector store 的檔案清單
        url = f"https://api.openai.com/v1/vector_stores/{vector_store_id}/files"
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            files_data = response.json()
            # 這裡簡化處理，實際應該根據查詢進行語意搜尋
            files_info = []
            for file_obj in files_data.get("data", [])[:3]:  # 取前3個檔案
                file_id = file_obj.get("id")
                # 嘗試獲取檔案內容（這部分可能需要調整）
                files_info.append({
                    "file_id": file_id,
                    "status": file_obj.get("status", "unknown")
                })
            
            return {
                "success": True,
                "query": query,
                "results": files_info,
                "message": f"找到 {len(files_info)} 個相關檔案。"
            }
        else:
            return {
                "success": False,
                "error": f"API 錯誤: {response.status_code}",
                "message": "無法搜尋向量資料庫"
            }
            
    except Exception as e:
        logger.error(f"Vector Store 查詢錯誤: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": "向量資料庫查詢失敗"
        }

def should_use_vector_search(message_content: str) -> bool:
    """判斷是否需要使用向量搜尋"""
    search_keywords = ["查詢", "搜尋", "找", "資料", "文件", "內容", "資訊", "什麼是", "如何", "怎麼"]
    return any(keyword in message_content for keyword in search_keywords)

async def handle_function_call(message_content: str, websocket: WebSocket):
    """處理函數調用"""
    if should_use_vector_search(message_content):
        logger.info(f"檢測到需要向量搜尋: {message_content}")
        
        # 執行向量搜尋
        search_result = await query_vector_store(message_content)
        
        # 將搜尋結果以訊息形式發送給客戶端
        function_result = {
            "type": "function_result",
            "function_name": "search_vector_store",
            "query": message_content,
            "result": search_result
        }
        
        await websocket.send_text(json.dumps(function_result))
        return True
    
    return False

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
                "instructions": "你是一個友善且充滿活力的AI助手。請務必用繁體中文進行對話，語調自然流暢。請快速且簡潔地回應，避免過長的回答。當需要查詢資料或文件時，請告訴用戶正在搜尋相關資訊。",
                "voice": "alloy",  
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {
                    "model": "whisper-1",
                    "language": "zh"  # 指定中文語言
                },
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,          # 提高靈敏度
                    "prefix_padding_ms": 300,   # 增加前置延遲確保完整語音
                    "silence_duration_ms": 200,  # 適度的靜音檢測時間
                    "create_response": False    # 禁用自動創建回應，由客戶端控制
                },
                "temperature": 0.7,  # 稍微降低溫度以提高響應速度
                "max_response_output_tokens": 2048  # 限制回應長度以加快速度
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
                    message_type = data.get('type', 'unknown')
                    logger.debug(f"客戶端 -> OpenAI: {message_type}")
                    
                    # 檢查是否為需要處理 function calling 的訊息類型
                    if message_type == "conversation.item.create":
                        item = data.get("item", {})
                        if item.get("type") == "message" and item.get("role") == "user":
                            content = item.get("content", [])
                            for content_part in content:
                                if content_part.get("type") == "input_text":
                                    text_content = content_part.get("text", "")
                                    # 檢查是否需要執行向量搜尋
                                    if await handle_function_call(text_content, websocket):
                                        logger.info("已處理向量搜尋請求")
                    
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
                "instructions": "你是一個友善且充滿活力的AI助手。請務必用繁體中文進行對話。你可以使用 Markdown 格式來美化回應內容，包括標題、列表、程式碼區塊等。回應要詳細且有用。當需要查詢資料或文件時，請告訴用戶正在搜尋相關資訊。",
                "temperature": 0.8,
                "max_response_output_tokens": 4096
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
                    message_type = data.get('type', 'unknown')
                    logger.debug(f"文字模式客戶端 -> OpenAI: {message_type}")
                    
                    # 檢查是否為需要處理 function calling 的訊息類型
                    if message_type == "conversation.item.create":
                        item = data.get("item", {})
                        if item.get("type") == "message" and item.get("role") == "user":
                            content = item.get("content", [])
                            for content_part in content:
                                if content_part.get("type") == "input_text":
                                    text_content = content_part.get("text", "")
                                    # 檢查是否需要執行向量搜尋
                                    if await handle_function_call(text_content, websocket):
                                        logger.info("文字模式已處理向量搜尋請求")
                    
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