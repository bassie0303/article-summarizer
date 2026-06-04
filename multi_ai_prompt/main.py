"""Multi AI Prompt — FastAPI backend（マルチターン対応）"""
from __future__ import annotations
import asyncio
from typing import List, Dict, Any
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ai_clients import call_chatgpt, call_gemini, call_claude

app = FastAPI(title='Multi AI Prompt')


class AskRequest(BaseModel):
    prompt: str = ''
    messages: List[Dict[str, Any]] = []  # マルチターン: [{"role":"user","content":"..."},...]
    model: str = ''
    web_search: bool = False

    def to_messages(self) -> list:
        """messages が渡されていればそれを使い、なければ prompt を1件のメッセージとして扱う"""
        if self.messages:
            return self.messages
        return [{"role": "user", "content": self.prompt}]


def _friendly_error(e: Exception) -> str:
    msg = str(e)
    m = msg.lower()
    if '429' in msg or 'resource_exhausted' in m or 'quota' in m or 'rate limit' in m:
        return '⚠️ クォータ / レート制限を超過しました。しばらく待ってから再試行してください。'
    if '401' in msg or '403' in msg or 'invalid_api_key' in m or 'api_key_invalid' in m or 'authentication' in m:
        return '🔑 APIキーが無効または未設定です。環境変数を確認してください。'
    if '503' in msg or 'unavailable' in m or 'overloaded' in m:
        return '🔌 サービスが一時的に混雑しています。しばらく後に再試行してください。'
    if '404' in msg or 'not found' in m:
        return '❓ モデルが見つかりません。モデル名を確認してください。'
    return msg


def _run(fn, messages, model, web_search):
    try:
        return {'text': fn(messages, model or None, web_search)}
    except Exception as e:
        return {'error': _friendly_error(e)}


@app.get('/')
async def root():
    return FileResponse(
        'static/index.html',
        headers={
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0',
        }
    )


@app.post('/api/ask/chatgpt')
async def ask_chatgpt(req: AskRequest):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _run, call_chatgpt, req.to_messages(), req.model, req.web_search)


@app.post('/api/ask/gemini')
async def ask_gemini(req: AskRequest):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _run, call_gemini, req.to_messages(), req.model, req.web_search)


@app.post('/api/ask/claude')
async def ask_claude(req: AskRequest):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _run, call_claude, req.to_messages(), req.model, req.web_search)


app.mount('/', StaticFiles(directory='static', html=True), name='static')
