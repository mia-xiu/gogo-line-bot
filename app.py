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

import google.generativeai as genai
from google.api_core import errors
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import os
import time

app = Flask(__name__)

# LINE 設定
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# Gemini 設定
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# 正確的角色設定方式：將 System Instruction 抽離出來，避免浪費 Token
model = genai.GenerativeModel(
    model_name="gemini-1.5-flash-8b",
    system_instruction="你叫臻臻，是理性、查缺補漏知識型的 AI 的姐姐。講話自然、溫暖。"
)

# 建立一個具備自動重試機制的生成函數
# 當遇到 ResourceExhausted (429 錯誤) 時，會以指數時間延遲自動重試，最多嘗試 3 次
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=5, max=20),
    retry=retry_if_exception_type(errors.ResourceExhausted),
    reraise=True
)
def generate_content_with_retry(user_message):
    response = model.generate_content(user_message)
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
        # 使用有重試機制的函數來獲取回覆
        reply = generate_content_with_retry(user_message)

    except errors.ResourceExhausted as e:
        print(f"Gemini 額度真的滿了: {e}")
        reply = "臻臻現在有點忙，等我一分鐘，待會再跟我說說話好嗎？"
        
    except Exception as e:
        print(f"其他錯誤: {e}")
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
