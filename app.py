#app.py

from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash
import yt_dlp
from pydub import AudioSegment
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
from openai import OpenAI
from flask_cors import CORS
from pymongo.mongo_client import MongoClient
from pymongo import MongoClient
import certifi
import re
from flask_dance.contrib.google import make_google_blueprint, google
from oauthlib.oauth2.rfc6749.errors import TokenExpiredError
from concurrent.futures import ThreadPoolExecutor, as_completed
import paypal_integration  # 引用另外創建的 PayPal 集成模組
from google.cloud import secretmanager, storage
import subprocess
import logging
from werkzeug.utils import secure_filename # 用於安全地處理文件名
import json
import requests
import smtplib # 用於發送電子郵件
from email.mime.text import MIMEText # 用於創建電子郵件正文
from email.mime.multipart import MIMEMultipart # 用於創建電子郵件
import uuid
import datetime
from datetime import datetime
import importlib.util

app = Flask(__name__)
CORS(app)

# 設定日誌級別和格式
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    # filename='/var/log/myapp.log',
    filename='myapp.log',  # 指定日誌文件的路徑
    filemode='a'  # 附加模式
)

# 封裝一個函數來決定從哪裡獲取秘密
def get_secret(secret_name):
    # 如果是 GAE 環境，從 Secret Manager 獲取
    if os.getenv('GAE_ENV', '').startswith('standard'):
        # 實例化 Secret Manager 客戶端
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/professor-x-419703/secrets/{secret_name}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    else:
        # 如果不是 GAE 環境，從 .env 文件載入
        return os.getenv(secret_name)

load_dotenv() 

# 使用 get_secret 函數來獲取各種配置
app.secret_key = get_secret("FLASK_SECRET_KEY")
mongo_uri = get_secret("MongoDB_url")
openai_api_key = get_secret("OPENAI_API_KEY")
google_client_id = get_secret("client_id")
google_client_secret = get_secret("client_secret")
paypal_client_id = get_secret("paypal_client_id")
paypal_secret = get_secret("paypal_secret")
CLOUD_STORAGE_BUCKET = get_secret("CLOUD_STORAGE_BUCKET")


# 設定mongoDB
app.config["MONGO_URI"] = mongo_uri
ca = certifi.where() # 設定這個就不會出現SSL憑證錯誤
client = MongoClient(mongo_uri, tlsCAFile=ca)
# 獲取資料庫和集合
db = client['myDatabase'] 
test_collection = db['test_collection']
content_db = db["contents"]
google_db = db["google_login"]
users_db = db['users']
email_subscriptions_db = db['email_subscriptions']

# 設置google login
google_bp = make_google_blueprint(
    client_id=google_client_id,
    client_secret=google_client_secret,
    redirect_to="index",
    scope=[
        "https://www.googleapis.com/auth/userinfo.email", 
        "https://www.googleapis.com/auth/userinfo.profile",
        "openid"
        ]

)
app.register_blueprint(google_bp, url_prefix="/login")

# 從環境變量中獲取 API 金鑰
client = OpenAI(
    api_key=openai_api_key,
)

# ======================== 基本設定 以上 ========================
# ======================== 進入頁面初始設定 以下 ========================

@app.route("/")
def welcome():
    return render_template('welcome02.html')

@app.route("/index")
def index():
    if not google.authorized:
        return redirect(url_for("google.login"))
    try:
        resp = google.get("/oauth2/v1/userinfo")
        if resp.ok:
            userinfo = resp.json()
            print("userinfo:",userinfo)

            google_id = userinfo.get("id")
            name = userinfo.get("name")
            email = userinfo.get("email") 
            given_name = userinfo.get("given_name")
            family_name = userinfo.get("family_name")
            
            
            # 構建要存儲的用戶信息字典
            user_info_to_store = {
                "google_id": google_id,  # Google ID
                "name": name,  # 使用者名稱
                "email": email,  # 電子郵件地址
                "given_name": given_name,  # 名字
                "family_name": family_name,  # 姓氏
                "last_bonus_date": None,
                "points": 0,
            }

            # 檢查數據庫是否已有該使用者
            existing_user = users_db.find_one({"google_id": google_id})
            if existing_user:
                # 如果使用者已存在
                consecutive_days = existing_user.get("consecutive_days", 0)
                user_info_to_store["last_bonus_date"] = existing_user.get("last_bonus_date")
                user_info_to_store["points"] = existing_user.get("points", 0)
                users_db.update_one({"google_id": google_id}, {"$set": user_info_to_store})
            else:
                # 如果使用者不存在，創建新使用者
                consecutive_days = 0  # 設置新用戶的連續天數為0
                users_db.insert_one(user_info_to_store)

            # 更新點數
            user_points = user_info_to_store["points"]
            last_bonus_date = user_info_to_store.get("last_bonus_date")
            current_date = datetime.now().date()

            # 檢查是否應該添加獎勵點數
            if last_bonus_date is None or current_date > last_bonus_date.date() + timedelta(days=30):
                user_points += 100
                users_db.update_one({"google_id": google_id}, {"$set": {
                    "points": user_points,
                    "last_bonus_date": datetime.combine(current_date, datetime.min.time())
                }})

            session['google_id'] = google_id
            session['name'] = name
            session['email'] = email
            session['given_name'] = given_name
            session['family_name'] = family_name
            session['user_points'] = user_points
            # print("session資訊：",session)
            logging.info(f"User {name} logged in. Points: {user_points}")
            print(f"User {name} logged in. Points: {user_points} Consecutive days: {consecutive_days}")


        else:
            return "無法獲取使用者資訊", 500
    except TokenExpiredError:
        return redirect(url_for("google.login"))  # 引導用戶重新登入
    
    return render_template('index.html', user_name=name, user_points=user_points, consecutive_days=consecutive_days)

# ======================== 進入頁面初始設定 以上 ========================

# ====================== 設定免費方案 以下 ======================
# class TranscriptionService:
#     def __init__(self, db):
#         self.db = db  # 傳入MongoDB的連接來處理配額數據

#     def check_quota(self, user_id):
#         """檢查用戶當日配額"""
#         today = datetime.now().date()
#         user_quota = self.db.users_db.find_one({"user_id": user_id, "date": today.strftime("%Y-%m-%d")})
#         if user_quota is None:
#             # 初始化配額
#             user_quota = {"user_id": user_id, "date": today.strftime("%Y-%m-%d"), "count": 0, "time_used": 0}
#             self.db.users_db.insert_one(user_quota)
#         return user_quota

#     def can_transcribe(self, user_id, audio_length):
#         """判斷用戶是否可以轉錄新的音訊"""
#         quota = self.check_quota(user_id)
#         if quota['count'] < 3 and quota['time_used'] + audio_length <= 15:
#             return True
#         return False

#     def update_quota(self, user_id, audio_length):
#         """更新用戶配額"""
#         if self.can_transcribe(user_id, audio_length):
#             self.db.users_db.update_one(
#                 {"user_id": user_id, "date": datetime.now().date().strftime("%Y-%m-%d")},
#                 {"$inc": {"count": 1, "time_used": audio_length}}
#             )
#             return True
#         return False

# # 初始化TranscriptionService
# transcription_service = TranscriptionService(client)

# ===================== 設定免費方案 以上 =====================

# ===================== 簽到設定 以下 =====================
@app.route("/checkin", methods=["POST"])
def checkin():
    google_id = session.get("google_id")
    if not google_id:
        return jsonify(success=False, message="尚未登錄")

    user = users_db.find_one({"google_id": google_id})
    if not user:
        return jsonify(success=False, message="找不到用戶")

    today = datetime.now().date()
    today_datetime = datetime.combine(today, datetime.min.time())
    checkin_dates = user.get("checkin_dates", [])
    last_checkin_date = checkin_dates[-1] if checkin_dates else None

    # 如果今日已簽到或最後一次簽到與今天同一天，直接返回
    if last_checkin_date == today_datetime:
        return jsonify(success=False, message="今日已簽到")
    
    # 計算連續簽到日數
    if last_checkin_date:
        delta = today - last_checkin_date.date()
        if delta.days == 1:
            consecutive_days = user.get("consecutive_days", 0) + 1
        else:
            consecutive_days = 1
    else:
        consecutive_days = 1

    points = user.get("points", 0)
    points += 5

    # 連續簽到7日獎勵50點
    if consecutive_days == 7:
        points += 50

    checkin_dates.append(today_datetime)

    users_db.update_one({"google_id": google_id}, {
        "$set": {
            "points": points,
            "checkin_dates": checkin_dates,
            "consecutive_days": consecutive_days
        }
    })

    session['user_points'] = points
    print(f"用戶 {google_id} 簽到成功，點數：{points}，已經連續簽到 {consecutive_days} 天")
    logging.info(f"User {google_id} checked in successfully. Points: {points}，Consecutive days: {consecutive_days}")
    return jsonify(success=True, points=points, consecutive_days=consecutive_days)

# ===================== 簽到設定 以上 =====================

# ===================== 功能設定 以下 =====================

# 從youtube獲取音訊資訊
@app.route('/get_video_info', methods=['POST'])
def get_video_info():
    data = request.json
    youtube_url = data['youtubeUrl']
    try:
        ydl_opts = {
            'format': 'bestaudio/best'
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
            video_title = info.get('title', 'DownloadedAudio')
            session['file_name'] = video_title
            duration = info.get('duration', 0)  # 獲取影片時長（秒）
            token_per_second = 0.0167  # 每秒0.00167個令牌
            estimated_tokens =  round(duration * token_per_second, 2)
            session['estimated_tokens'] = estimated_tokens
            print("estimated_tokens:", estimated_tokens)
            logging.info(f"Video info retrieved: Duration: {duration} seconds, Estimated tokens: {estimated_tokens}")

        #檢查用戶點數是否足夠
        user_points = session.get('user_points', 0)
        if user_points < estimated_tokens:
            logging.error(f"User: {session.get('name')} has insufficient points.")
            return jsonify({"success": False, "message": "點數不足，請儲值"}), 400

        return jsonify({"success": True, "duration": duration, "estimatedTokens": estimated_tokens, "videoTitle": video_title})
    except Exception as e:
        print("錯誤訊息:", str(e))
        logging.error(f"Error getting video info: {str(e)}")
        return jsonify({"success": False, "message": "請輸入正確的Youtube網址"}), 500

# 上傳音訊檔案並取得資訊
@app.route('/upload_file', methods=['POST'])
def upload_file():
    file = request.files['audioFile']
    logging.info(f"File received: {file}")
    filename = secure_filename(file.filename)
    download_dir = "./download"
    file_path = os.path.join(download_dir, filename)
    logging.info(f"Uploading file: {filename}")
    file.save(file_path)
    audio_length = len(AudioSegment.from_file(file_path)) / 1000.0
    estimated_cost = round(audio_length * 0.0167, 2)
    session['estimated_cost'] = estimated_cost
    print("audio_length:", audio_length)
    print("estimated_cost:", estimated_cost)
    print("filename:", filename)

    #檢查用戶點數是否足夠
    user_points = session.get('user_points', 0)
    if user_points < estimated_cost:
        logging.error(f"User: {session.get('name')} has insufficient points.")
        return jsonify({"success": False, "message": "點數不足，請儲值"}), 400

    logging.info(f"File uploaded: {filename}, Length: {audio_length} seconds, Estimated cost: {estimated_cost} tokens")
    return jsonify(success=True, fileName=filename, audioLength=audio_length, estimatedCost=estimated_cost)


# 扣除點數
def deduct_user_points(user_id, points_to_deduct):
    try:
        user_points = float(session.get('user_points', 0))
        points_to_deduct = float(points_to_deduct)
        if user_points >= points_to_deduct:
            new_points = round(user_points - points_to_deduct, 2)
            result = users_db.update_one({"google_id": user_id}, {"$set": {"points": new_points}})
            if result.modified_count == 1:
                session['user_points'] = new_points  # 確保只有在數據庫更新成功時才更新會話
                logging.info(f"User {user_id} deducted {points_to_deduct} points. Remaining points: {new_points}")
                return True, "點數扣除成功"
            else:
                raise Exception("Database update failed")
        else:
            logging.error(f"User {user_id} has insufficient points.")
            return False, "點數不足"
    except ValueError:
        logging.error("Invalid input for points to deduct")
        return False, "無效的點數輸入"
    except Exception as e:
        logging.error(f"Error deducting points: {str(e)}")
        return False, "數據庫錯誤"
    


# def upload_to_gcs(local_file_path, gcs_bucket_name, gcs_file_path):
#     try:
#         client = storage.Client()
#         bucket = client.get_bucket(gcs_bucket_name)
#         blob = bucket.blob(gcs_file_path)
#         blob.upload_from_filename(local_file_path)

#         return "Upload successful"
#     except Exception as e:
#         return f"Error during upload to GCS: {str(e)}"

# 處理檔案名稱
def sanitize_filename(filename):
    # 將空格替換為下劃線
    filename = filename.replace(" ", "_")
    # 移除或替換特殊字符，只保留字母、數字、下劃線和點
    filename = re.sub(r'[^a-zA-Z0-9_\.-]', '', filename)
    return filename


# 下載 YouTube 音訊
def download_youtube_audio_as_mp3(youtube_url):
    os.umask(0o002)  # 設置 umask 以確保新創建的文件具有適當的群組寫入權限

    try:
        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        # print("tmp file:", os.listdir("/tmp"))
        
        # 測試創建檔案
        # create_test_file()

        logging.info(f"Downloading audio from YouTube: {youtube_url}")

        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'noplaylist': True,  # 不要下載播放清單
            'verbose': True  # 詳細日誌
        }

        try:
            logging.debug("Preparing to extract video info.")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(youtube_url, download=False)
            logging.debug("Video info extracted.")

            video_title = info.get('title', 'DownloadedAudio')
            current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{video_title}_{current_time}.mp3"
            ydl_opts['outtmpl'] = f"./download/{filename[:-4]}"  # 更新選項中的檔案名模板，包含副檔名

            logging.debug("Starting download of the video.")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([youtube_url])
            logging.debug(f"Download completed. File saved as: {filename}")

        except Exception as e:
            logging.error("Failed to download or process video", exc_info=True)

        # 上傳到GCS
        # result = upload_to_gcs(f"/tmp/{filename}", CLOUD_STORAGE_BUCKET, filename)
        # return result # 測試用
        return segment_audio(filename, 5)  # 假設分段長度為5分鐘

    except Exception as e:
        logging.error(f"Error during download: {str(e)}")
        return f"Error during upload: {str(e)}"



# 音訊分段
def segment_audio(filename, segment_length_minutes):
    download_dir = "./download"
    segment_length_ms = segment_length_minutes * 60 * 1000
    full_path = os.path.join(download_dir, filename)  # 使用 os.path.join 確保路徑正確

    try:
        audio = AudioSegment.from_file(full_path)
        
        segments = []
        start = 0
        part = 1
        while start < len(audio):
            end = start + segment_length_ms
            segment = audio[start:end]
            segment_filename = f"{filename[:-4]}_{str(part).zfill(2)}.mp3" # [:-4]移除檔案擴展名
            full_segment_path = os.path.join(download_dir, segment_filename)
            print(f"full_segment_path: {full_segment_path}")
            segment.export(full_segment_path, format="mp3")
            segments.append(full_segment_path)   # 將檔案路徑加入列表
            start += segment_length_ms
            part += 1

        os.remove(full_path)  # 在完成所有分段工作後刪除原始檔案
        logging.info(f"Audio segmented into {len(segments)} parts.")
        return segments  # 返回分段檔案的路徑列表
    except Exception as e:
        logging.error(f"Error processing file {filename}: {str(e)}")
        return []

# 音訊轉文字
# def transcribe_audio(segment_files):
#     transcriptions = []
#     for filename in segment_files:
#         try:
#             with open(filename, "rb") as audio_file:
#                 transcription = client.audio.transcriptions.create(
#                 model="whisper-1", 
#                 file=audio_file,
#                 )
#                 transcriptions.append(transcription.text)

#             os.remove(filename) # 刪除處理過的音訊檔案
#         except FileNotFoundError:
#             print(f"檔案 {filename} 不存在。")
#         except Exception as e:
#             print(f"處理檔案 {filename} 時發生錯誤：{e}")
    
#     return " ".join(transcriptions)  # 將所有片段的轉寫結果合併

def transcribe_segment(filename, index, add_timestamp):
    """處理單個音訊文件的轉寫，返回包括索引的結果"""
    response_format="srt" if add_timestamp else "text"

    try:
        with open(filename, "rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                model="whisper-1", 
                file=audio_file,
                response_format=response_format
            )
            print(f"transcribe_segment {index}: Transcription successful.")
            logging.info(f"Transcription of segment {index} successful.")
            logging.info(f"Add_timestamp: {add_timestamp}, Transcription: {transcription}")

            return index, transcription
            
    except FileNotFoundError:
        print(f"檔案 {filename} 不存在。")
        logging.error(f"File {filename} not found.")
    except Exception as e:
        print(f"處理檔案 {filename} 時發生錯誤：{e}")
        logging.error(f"Error processing file {filename}: {e}")
    finally:
        if os.path.exists(filename):
            os.remove(filename)  # 確保即使出現錯誤也刪除處理過的音訊檔案
    return index, ""

def transcribe_audio(segment_files, add_timestamp):
    """並行處理所有音訊分段的轉寫，確保按原始順序組合結果"""
    transcriptions = [None] * len(segment_files)  # 初始化結果列表，大小與分段數相同
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(transcribe_segment, filename, i, add_timestamp) for i, filename in enumerate(segment_files)]
        for future in as_completed(futures):
            index, transcription_result = future.result()
            transcriptions[index] = transcription_result  # 按索引放置轉寫結果
    print("transcribe_audio: All segments transcribed.")
    logging.info(f"All segments transcribed.")
    return " ".join(filter(None, transcriptions))  # 組合所有轉寫結果，並過濾掉任何 None 值


# 文字摘要
def summarize_text(text):
    response = client.chat.completions.create(
        messages=[
                {"role": "system", "content": "你是專業的重點整理專家，用淺顯易懂的語句有條理的把重點整理出來。根據文本的語言輸出，如果是中文則只使用繁體中文字，不要用簡體字。"},
                {"role": "user", "content": text}
        ],
        model="gpt-4o", #"gpt-3.5-turbo",
    )
    print(f'summarize_text: {response.usage.prompt_tokens} prompt tokens used.')
    logging.info(f"{response.usage.prompt_tokens} prompt tokens used.")
    return response.choices[0].message.content


# youtube音訊轉文字
@app.route('/process_video', methods=['POST'])
def process_video():
    data = request.json
    logging.info(f"Data received: {data}")
    youtube_url = data['youtubeUrl']
    add_timestamp = data['YT_addTimestamp']
    logging.info(f"add_timestamp: {add_timestamp}")
    estimated_tokens = session.get('estimated_tokens', 0)
    logging.info(f"START Processing video: {youtube_url}")

    # 針對該用戶檢查URL是否已經處理過
    google_id = session.get('google_id')  # 獲取使用者的Google ID
    existing_content = content_db.find_one({"url": youtube_url, "google_id": google_id})
    if existing_content:
        # 如果URL已經存在，返回提示
        logging.info("Video already processed.")
        return jsonify({"success": False, "message": "已經處理過囉！"})

    # 全面檢查URL是否已經處理過
    checkall_existing_content = content_db.find_one({"url": youtube_url})
    if checkall_existing_content:
        # 如果找到相關記錄，則直接回傳存在的資料
        logging.info("Video already processed by another user.")
        return jsonify({
            "success": True,
            "transcription": checkall_existing_content["transcription"],
            "summary": checkall_existing_content["summary"],
            "file_name": checkall_existing_content["file_name"]
        })
    # 沒有處理過的URL
    logging.info(f"Not yet processed video: {youtube_url}")

    # 語音轉文字
    segment_files = download_youtube_audio_as_mp3(youtube_url) # 返回分段音訊檔案的路徑列表
    print("segment_files:", segment_files)
    transcription = transcribe_audio(segment_files, add_timestamp)
    summary = summarize_text(transcription)

    # 處理重點整理換行
    summary = "\n" + summary  # 在開頭添加換行符，以處理首個條目
    summary = re.sub(r"\n(\d+\.)", r"\n\1", summary)  # 在每個數字點前加上換行符
    summary = summary.lstrip("\n")  # 移除開頭多餘的換行符

    # category_id = data.get('categoryId') # 分類
    share = data.get('share', False)  # 預設不分享
    google_id = session.get('google_id') # 獲取使用者的Google ID
    file_name = session.get('file_name')  # 從會話中獲取檔案名稱

    content_data = {
        "google_id": google_id,
        "file_name": file_name,
        "url": youtube_url,
        "category_id": "category_id", # 暫時沒有分類ID
        "transcription": transcription,
        "summary": summary,
        "shared": share,
        "timestamp": datetime.now()
    }
    try:
        content_db.insert_one(content_data)
        print("Content saved successfully.")
        logging.info("Content saved successfully.")

        # 數據保存成功後扣除點數
        success, message = deduct_user_points(google_id, estimated_tokens)
        if not success:
            logging.error("Failed to deduct points after saving content.")
            raise Exception(message) 
        
    except Exception as e:
        print({"success": False, "message": str(e)})
        logging.error(f"Error saving content: {str(e)}")

    return jsonify({
    'success': True,
    'transcription': transcription,
    'summary': summary,
    'file_name': file_name,
    'new_points': session.get('user_points', 0)  # 返回更新後的點數  
})


# 上傳的mp3檔案轉文字
@app.route('/process_audio', methods=['POST'])
def process_audio():
    data = request.json
    user_id = session.get('google_id')
    filename = data.get('fileName')
    audio_length = data.get('audioLength', 0)  # 獲取音訊長度
    add_timestamp = data.get('Audio_addTimestamp')
    estimated_cost = session.get('estimated_cost', 0)

    # if not transcription_service.can_transcribe(user_id, audio_length):
    #     return jsonify({"success": False, "message": "今日轉錄次數已達上限或超過單次轉錄時間上限"}), 403


    # 語音轉文字
    segment_files = segment_audio(filename, 5) # 返回分段音訊檔案的路徑列表
    print("segment_files:", segment_files)
    transcription = transcribe_audio(segment_files, add_timestamp).replace(" ", "\n")
    summary = summarize_text(transcription)

    # 處理重點整理換行
    summary = "\n" + summary  # 在開頭添加換行符，以處理首個條目
    summary = re.sub(r"\n(\d+\.)", r"\n\1", summary)  # 在每個數字點前加上換行符
    summary = summary.lstrip("\n")  # 移除開頭多餘的換行符

    # category_id = data.get('categoryId') # 分類
    share = data.get('share', False)  # 預設不分享
    google_id = session.get('google_id') # 獲取使用者的Google ID
    file_name = segment_files[0].split("/")[-1][:-3]  # 從路徑中提取檔案名稱

    content_data = {
        "google_id": google_id,
        "file_name": file_name,
        "url": "user_upload",
        "category_id": "category_id", # 暫時沒有分類ID
        "transcription": transcription,
        "summary": summary,
        "shared": share,
        "timestamp": datetime.now()
    }
    try:
        content_db.insert_one(content_data)
        print("Content saved successfully.")
        logging.info("Content saved successfully.")

        # 數據保存成功後扣除點數
        success, message = deduct_user_points(google_id, estimated_cost)

        # # 更新免費方案配額
        # transcription_service.update_quota(user_id, audio_length)
        # logging.info(f"User {user_id} quota updated after transcription.")

        if not success:
            logging.error("Failed to deduct points after saving content.")
            raise Exception(message)  # Optionally handle this situation
        
    except Exception as e:
        print({"success": False, "message": str(e)})
        logging.error(f"Error saving content: {str(e)}")

    return jsonify({
    'success': True,
    'transcription': transcription,
    'summary': summary,
    'file_name': file_name,
    'new_points': session.get('user_points', 0)  # 返回更新後的點數   
    })


# ===================== 功能設定 以上 =====================
# ===================== 匯出檔案 以下 =====================

@app.route('/download_transcription', methods=['GET'])
def download_transcription():
    filename = request.args.get('filename')
    if filename:
        filepath = os.path.join('path/to/transcriptions', filename)
        if os.path.exists(filepath):
            return send_file(filepath, as_attachment=True)
        else:
            return "File not found", 404
    else:
        return "Filename not provided", 400

# ===================== 匯出檔案 以上 =====================

# 點擊標籤顯示內容
@app.route('/get_video_content', methods=['POST'])
def get_video_content():
    data = request.json
    youtube_url = data.get('youtubeUrl')
    google_id = session.get('google_id')
    content = content_db.find_one({"url": youtube_url, "google_id": google_id})
    if content:
        return jsonify({
            "success": True,
            "transcription": content["transcription"],
            "summary": content["summary"]
        })
    else:
        logging.error("get_video_content() Content not found.")
        return jsonify({"success": False, "message": "Content not found."}), 404


# 頁面加載時取得用戶標籤
@app.route('/get_user_contents', methods=['GET'])
def get_user_contents():
    google_id = session.get('google_id')
    if not google_id:
        logging.error("get_user_contents() User not logged in.")
        return jsonify({"success": False, "message": "尚未有內容"}), 401

    contents = content_db.find({"google_id": google_id}).sort("timestamp", -1)
    content_list = [{"file_name": content["file_name"], "url": content["url"], "timestamp": content["timestamp"]} for content in contents]
    
    return jsonify({"success": True, "contents": content_list})







# 讓使用者根據分類檢索內容
@app.route('/contents/<category_id>', methods=['GET'])
def get_contents_by_category(category_id):
    contents = db.contents.find({"category_id": category_id, "shared": True})
    results = []
    for content in contents:
        results.append({
            "transcription": content["transcription"],
            "summary": content["summary"],
            "timestamp": content["timestamp"]
        })
    return jsonify(results)


# ========== 付款相關 以下 ==========

# 支付頁面
@app.route('/payment')
def payment():
    user_points = session.get('user_points', 0)  # 如果沒有找到，預設為 0
    name = session.get('name')
    logging.info(f"User {name} accessing payment page.")
    return render_template('payment.html', user_name=name, user_points=user_points)

# 初始化 PayPal
paypal_integration.init_paypal(paypal_client_id, paypal_secret)

@app.route('/pay/<amount>')
def pay(amount):
    try:
        payment_url = paypal_integration.create_payment(app, amount)  # 接受金額作為參數
        # 把amount存到session
        session['amount'] = amount
        logging.info(f"amount: {amount}")
        if payment_url:
            return redirect(payment_url)
        else:
            session.pop('amount', None)
            logging.error("Unable to create payment")
            return 'Unable to create payment'
    except Exception as e:
        session.pop('amount', None)
        logging.error(f"Error creating payment: {str(e)}")
        return str(e)

def calculate_points_based_on_amount(amount):
    # 定義每個計劃的點數
    plans = {
        '1': 100.00,  # 假設 $1 購買 100 點
        '10': 1200.00, # 假設 $10 購買 1200 點
        '20': 3000.00, # 假設 $20 購買 3000 點
        '30': 6000.00, # 假設 $30 購買 6000 點
    }
    return plans.get(amount, 0)


@app.route('/payment_completed')
def payment_completed():
    payment_id = request.args.get('paymentId')
    payer_id = request.args.get('PayerID')
    success, payment_details = paypal_integration.execute_payment(payment_id, payer_id)
    logging.info(f"payment_id: {payment_id}, payer_id: {payer_id}")
    logging.info(f"Payment completed: {success}, {payment_details}")

    if success:
        actual_paid_amount = session.get('amount')
        logging.info(f"Actual paid amount: {actual_paid_amount}")
        points = calculate_points_based_on_amount(actual_paid_amount)  # 計算應增加的點數
        google_id = session.get('google_id')
        
        if google_id:
            # 使用 MongoDB 的 $inc 更新操作來增加點數
            result = users_db.update_one(
                {"google_id": google_id},
                {"$inc": {"points": points}}
            )
            
            if result.modified_count > 0:
                logging.info(f"User {google_id} received {points} points.")
                flash(f'Payment successful! You now have {points} additional points.', 'success')
            else:
                logging.error("Failed to update user points.")
                flash('Error updating your points. Please contact support.', 'error')
        else:
            logging.error("User not logged in.")
            flash('You need to log in to receive points.', 'error')
    else:
        session.pop('amount', None)
        logging.error("Payment failed.")
        flash('Payment failed. Please try again.', 'error')
    
    return redirect(url_for('index'))

@app.route('/payment_cancelled')
def payment_cancelled():
    logging.info("Payment cancelled by the user.")
    flash("Payment cancelled by the user")  # Store the cancellation message
    return redirect(url_for('index'))  # Redirect to the homepage

# ========== 綠界金流 以下 ==========
# 動態載入 ECPay SDK
spec = importlib.util.spec_from_file_location(
    "ecpay_payment_sdk",
    "ecpay_payment_sdk.py"
)
ecpay_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ecpay_module)

# ECPay 支付 SDK 實體
ecpay_payment_sdk = ecpay_module.ECPayPaymentSdk(
    MerchantID=os.getenv("MerchantID"),
    HashKey=os.getenv("ECPAY_HASHKEY"),
    HashIV=os.getenv("ECPAY_HASHIV"),
)

@app.route('/ecpayment', methods=['POST'])
def ecpayment():
    order_params = {
        'MerchantTradeNo': datetime.now().strftime("NO%Y%m%d%H%M%S"),
        'StoreID': '',
        'MerchantTradeDate': datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
        'PaymentType': 'aio',
        'TotalAmount': "30",
        'TradeDesc': '訂單',
        'ItemName': '點數 100點',
        'ReturnURL': 'https://你的網站.com/return_url',
        'ChoosePayment': 'ALL',
        'ClientBackURL': 'https://你的網站.com/client_back_url',
        'ItemURL': 'https://你的網站.com/item_url',
        'Remark': '交易備註',
        'ChooseSubPayment': '',
        'OrderResultURL': 'https://professor-x.lillian-ai.com/order_result',
        'NeedExtraPaidInfo': 'Y',
        'DeviceSource': '',
        'IgnorePayment': '',
        'PlatformID': '',
        'InvoiceMark': 'N',
        'CustomField1': '',
        'CustomField2': '',
        'CustomField3': '',
        'CustomField4': '',
        'EncryptType': 1,
    }

    logging.info(f"Order params: {order_params}")

    try:
        # 產生綠界訂單所需參數
        final_order_params = ecpay_payment_sdk.create_order(order_params)

        # 產生 HTML 的 form 格式
        # action_url = 'https://payment-stage.ecpay.com.tw/Cashier/AioCheckOut/V5'  # 測試環境 記得.env也要改！！！
        action_url = 'https://payment.ecpay.com.tw/Cashier/AioCheckOut/V5' # 正式環境 記得.env也要改！！！
        html = ecpay_payment_sdk.gen_html_post_form(action_url, final_order_params)
        return html
    except Exception as error:
        return 'An exception happened: ' + str(error)


@app.route('/order_result', methods=['POST'])
def order_result():
    try:
        result = request.form.to_dict()
        app.logger.info(f'Order result: {result}')

        if 'RtnCode' in result and result['RtnCode'] == '1':  # 確認交易成功
            actual_paid_amount = int(result.get('TradeAmt') / 30) # 台幣換美金
            logging.info(f"Actual paid amount: {actual_paid_amount}")
            points = calculate_points_based_on_amount(actual_paid_amount)  # 計算應增加的點數
            google_id = session.get('google_id')
            
            if google_id:
                # 使用 MongoDB 的 $inc 更新操作來增加點數
                result = users_db.update_one(
                    {"google_id": google_id},
                    {"$inc": {"points": points}}
                )
                
                if result.modified_count > 0:
                    logging.info(f"User {google_id} received {points} points.")
                    flash(f'Payment successful! You now have {points} additional points.', 'success')
                else:
                    logging.error("Failed to update user points.")
                    flash('Error updating your points. Please contact support.', 'error')
            else:
                logging.error("User not logged in.")
                flash('You need to log in to receive points.', 'error')
        else:
            logging.error("Payment failed or was not completed.")
            flash('Payment failed. Please try again.', 'error')

        return render_template('order_result.html')
    except Exception as e:
        app.logger.error(f'Error processing order result: {str(e)}')
        return 'Error'


# ========== 綠界金流 以上 ==========

# ========== 付款相關 以上 ==========
# ========== Email訂閱 以下 ==========

# 配置SMTP服務器
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USERNAME = "wahao777@gmail.com"
SMTP_PASSWORD = "Funky8211"

# 發送Email的函數
def send_confirmation_email(to_email):
    msg = MIMEMultipart()
    msg["From"] = SMTP_USERNAME
    msg["To"] = to_email
    msg["Subject"] = "Lillian-AI 訂閱確認"

    body = "謝謝您的訂閱Lillian-AI！\n\n" \
           "如有最新消息將會立即通知您！"
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SMTP_USERNAME, to_email, msg.as_string())
            logging.info(f"Confirmation email sent to {to_email}")
    except Exception as e:
        logging.error(f"Error sending email: {e}")



# 新增訂閱Email的端點
@app.route("/emailsubscribe", methods=["POST"])
def subscribe():
    data = request.get_json()
    email = data.get('email')

    if not email or '@' not in email:
        return jsonify({"success": False, "message": "請提供有效的Email地址"}), 400

    email_subscriptions = {
        "email": email,
        "timestamp": datetime.now()
    }

    try:
        email_subscriptions_db.insert_one(email_subscriptions)
        send_confirmation_email(email)
        logging.info(f"New subscription added: {email}")
        return jsonify({"success": True, "message": "訂閱成功！"})
    except Exception as e:
        logging.error(f"Error adding subscription: {e}")
        return jsonify({"success": False, "message": "訂閱失敗，請重試。"}), 500




if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True) # 部署環境使用


# 開發階段不使用HTTPS，終端機輸入：
# export OAUTHLIB_INSECURE_TRANSPORT=1 
