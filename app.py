from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.exceptions import InvalidSignatureError

# 採用 Google 2026 最新官方 SDK 導入方式
from google import genai
from google.genai import types
from google.genai.errors import APIError

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import os

app = Flask(__name__)

# LINE 設定
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# Gemini 最新版初始化 (它會自動去抓環境變數中的 GEMINI_API_KEY)
client = genai.Client()

# 定義最新的系統角色設定
system_instruction = "你叫臻臻，是理性、查缺補漏知識型的 AI 的姐姐。講話自然、溫暖。"

# 具備自動重試機制的生成函數
# 當遇到 APIError (包含 429 額度超限) 時，會自動延遲並重試
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=5, max=20),
    retry=retry_if_exception_type(APIError),
    reraise=True
)
def generate_content_with_retry(user_message):
    # 改用新版 client.models.generate_content 語法，並換上穩定支援的 gemini-2.0-flash
    response = client.models.generate_content(
        model='gemini-2.0-flash',
        contents=user_message,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction
        )
    )
    return response.text

@app.route("/webhook", methods=['POST'])
def webhook():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_message = event.message.text

    try:
        # 呼叫重試函數
        reply = generate_content_with_retry(user_message)

    except APIError as e:
        # 新版 SDK 的錯誤捕捉，如果是 429 或是其他 API 限制
        print(f"Gemini API 錯誤: {e}")
        reply = "臻臻現在有點忙，等我一分鐘，待會再跟我說說話好嗎？"
        
    except Exception as e:
        print(f"其他不可預期錯誤: {e}")
        reply = "臻臻剛才恍神了 ，可以再說一次嗎？"

    # 發送 LINE 訊息
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[
                    TextMessage(text=reply)
                ]
            )
        )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
