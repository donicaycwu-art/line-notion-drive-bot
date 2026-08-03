import io, os, pickle, base64, datetime
from zoneinfo import ZoneInfo
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
GDRIVE_FOLDER_ID = os.environ["GDRIVE_FOLDER_ID"]
TOKEN_FILE = "token.pickle"
TW_TZ = ZoneInfo("Asia/Taipei")
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

def get_drive_service():
    token_b64 = os.environ.get("GDRIVE_TOKEN_B64")
    if token_b64:
        creds = pickle.loads(base64.b64decode(token_b64))
    else:
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)
    return build("drive", "v3", credentials=creds)

def get_display_name(event):
    try:
        with ApiClient(configuration) as c:
            api = MessagingApi(c)
            uid = event.source.user_id
            if event.source.type == "group":
                profile = api.get_group_member_profile(event.source.group_id, uid)
            elif event.source.type == "room":
                profile = api.get_room_member_profile(event.source.room_id, uid)
            else:
                profile = api.get_profile(uid)
            return profile.display_name
    except Exception as e:
        print(f"取得顯示名稱失敗：{e}")
        return event.source.user_id or "unknown"

def get_or_create_folder(service, name, parent_id):
    safe_name = name.replace("'", "\\'")
    query = (
        f"'{parent_id}' in parents and name = '{safe_name}' "
        "and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    result = service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
    folders = result.get("files", [])
    if folders:
        return folders[0]["id"]
    folder_metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = service.files().create(body=folder_metadata, fields="id").execute()
    return folder.get("id")

def upload_to_drive(file_content, filename, mimetype, sender_name):
    service = get_drive_service()
    user_folder_id = get_or_create_folder(service, sender_name, GDRIVE_FOLDER_ID)
    file_metadata = {"name": filename, "parents": [user_folder_id]}
    media = MediaIoBaseUpload(io.BytesIO(file_content), mimetype=mimetype, resumable=True)
    file = service.files().create(body=file_metadata, media_body=media, fields="id, webViewLink").execute()
    print(f"上傳成功：{sender_name}/{filename}")
    return file.get("webViewLink", "")

def ts(prefix, ext):
    now = datetime.datetime.now(TW_TZ)
    return f"{prefix}_{now.strftime('%Y%m%d_%H%M%S')}.{ext}"

def dl(mid):
    with ApiClient(configuration) as c:
        return MessagingApiBlob(c).get_message_content(mid)

def reply(token, text):
    with ApiClient(configuration) as c:
        MessagingApi(c).reply_message(ReplyMessageRequest(reply_token=token, messages=[TextMessage(text=text)]))
@app.route("/", methods=["GET"])
def health():
    return "OK", 200
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
    name = get_display_name(event)
    f = ts("image", "jpg")
    upload_to_drive(dl(event.message.id), f, "image/jpeg", name)

@handler.add(MessageEvent, message=VideoMessageContent)
def handle_video(event):
    name = get_display_name(event)
    f = ts("video", "mp4")
    upload_to_drive(dl(event.message.id), f, "video/mp4", name)

@handler.add(MessageEvent, message=FileMessageContent)
def handle_file(event):
    name = get_display_name(event)
    ext = event.message.file_name.rsplit(".", 1)[-1] if "." in event.message.file_name else "bin"
    f = ts("file", ext)
    upload_to_drive(dl(event.message.id), f, "application/octet-stream", name)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
