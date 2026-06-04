"""各 AI への並列リクエスト（Web検索・マルチターン対応）"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
import config


def call_chatgpt(messages: list, model: str | None = None, web_search: bool = False) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    use_model = "gpt-4o-search-preview" if web_search else (model or config.OPENAI_MODEL)
    resp = client.chat.completions.create(
        model=use_model,
        messages=messages,
    )
    return resp.choices[0].message.content or ''


def call_gemini(messages: list, model: str | None = None, web_search: bool = False) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=config.GEMINI_API_KEY)

    # Gemini は role が "user" / "model"（"assistant" ではない）
    contents = [
        {"role": "user" if m["role"] == "user" else "model",
         "parts": [{"text": m["content"]}]}
        for m in messages
    ]

    cfg = None
    if web_search:
        cfg = types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )

    resp = client.models.generate_content(
        model=model or config.GEMINI_MODEL,
        contents=contents,
        config=cfg,
    )
    return resp.text or ''


def _duckduckgo_search(query: str) -> str:
    """DuckDuckGo で検索して上位5件のスニペットを返す（APIキー不要）"""
    from duckduckgo_search import DDGS
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=5))
    if not results:
        return "検索結果が見つかりませんでした。"
    return "\n\n".join(
        f"【{r['title']}】\n{r['body']}\n出典: {r['href']}" for r in results
    )


def call_claude(messages: list, model: str | None = None, web_search: bool = False) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    final_messages = list(messages)

    if web_search:
        # 最後のユーザーメッセージに検索結果を埋め込む
        for i in range(len(final_messages) - 1, -1, -1):
            if final_messages[i]["role"] == "user":
                original = final_messages[i]["content"]
                search_results = _duckduckgo_search(original)
                enhanced = (
                    f"以下のWeb検索結果を参考にして質問に答えてください。\n\n"
                    f"=== 検索結果 ===\n{search_results}\n\n"
                    f"=== 質問 ===\n{original}"
                )
                final_messages[i] = {"role": "user", "content": enhanced}
                break

    msg = client.messages.create(
        model=model or config.ANTHROPIC_MODEL,
        max_tokens=4096,
        messages=final_messages,
    )
    return msg.content[0].text


SERVICES = {
    'chatgpt': call_chatgpt,
    'gemini':  call_gemini,
    'claude':  call_claude,
}


def send_to_all(messages: list, models: dict | None = None,
                web_search: bool = False) -> dict[str, str]:
    """3サービスに並列送信し {id: response_or_error} を返す"""
    models = models or {}
    results: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {
            ex.submit(fn, messages, models.get(ai_id), web_search): ai_id
            for ai_id, fn in SERVICES.items()
        }
        for future in as_completed(futures):
            ai_id = futures[future]
            try:
                results[ai_id] = future.result()
            except Exception as e:
                results[ai_id] = f'❌ エラー: {e}'

    return results
