import io, os, pickle, base64, datetime
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, ImageMessageContent, VideoMessageContent, AudioMessageContent, FileMessageContent
from linebot.v3.messaging import MessagingApiBlob
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

app = Flask(__name__)
LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
TARGET_USER_IDS = {uid.strip() for uid in os.environ["TARGET_USER_IDS"].split(",") if uid.strip()}
GDRIVE_FOLDER_ID = os.environ["GDRIVE_FOLDER_ID"]
TOKEN_FILE = "token.pickle"
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

def get_drive_service():
    # 優先從環境變數讀取（雲端部署用），本機沒有設定時退回讀 token.pickle 檔案
    token_b64 = os.environ.get("GDRIVE_TOKEN_B64")
    if token_b64:
        creds = pickle.loads(base64.b64decode(token_b64))
    else:
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)
    return build("drive", "v3", credentials=creds)

def upload_to_drive(file_content, filename, mimetype):
    service = get_drive_service()
    file_metadata = {"name": filename, "parents": [GDRIVE_FOLDER_ID]}
    media = MediaIoBaseUpload(io.BytesIO(file_content), mimetype=mimetype, resumable=True)
    file = service.files().create(body=file_metadata, media_body=media, fields="id, webViewLink").execute()
    print(f"上傳成功：{filename}")
    return file.get("webViewLink", "")

def ts(prefix, ext):
    return f"{prefix}_{datetime.datetime.now().strftime(chr(37)+'Y'+chr(37)+'m'+chr(37)+'d_'+chr(37)+'H'+chr(37)+'M'+chr(37)+'S')}.{ext}"

def dl(mid):
    with ApiClient(configuration) as c:
        return MessagingApiBlob(c).get_message_content(mid)

def reply(token, text):
    with ApiClient(configuration) as c:
        MessagingApi(c).reply_message(ReplyMessageRequest(reply_token=token, messages=[TextMessage(text=text)]))

@app.route("/callback", methods=["POST"])
def callback():
    sig = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, sig)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@handler.add(MessageEvent)
def handle_all(event):
    print(f"User ID：{event.source.user_id}（來源類型：{event.source.type}）")

@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image(event):
    if event.source.user_id not in TARGET_USER_IDS: return
    f = ts("image", "jpg")
    upload_to_drive(dl(event.message.id), f, "image/jpeg")
    reply(event.reply_token, f"圖片已備份！{f}")

@handler.add(MessageEvent, message=VideoMessageContent)
def handle_video(event):
    if event.source.user_id not in TARGET_USER_IDS: return

    f = ts("video", "mp4")
    upload_to_drive(dl(event.message.id), f, "video/mp4")
    reply(event.reply_token, f"視訊已備份！{f}")

@handler.add(MessageEvent, message=FileMessageContent)
def handle_file(event):
    if event.source.user_id not in TARGET_USER_IDS: return
    ext = event.message.file_name.rsplit(".", 1)[-1] if "." in event.message.file_name else "bin"
    f = ts("file", ext)
    upload_to_drive(dl(event.message.id), f, "application/octet-stream")
    reply(event.reply_token, f"文件已備份！{f}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
