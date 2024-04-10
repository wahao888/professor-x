from flask import Flask, request, jsonify, render_template, redirect, url_for
import yt_dlp
from pydub import AudioSegment
import os
from dotenv import load_dotenv
from datetime import datetime
from openai import OpenAI
from flask_cors import CORS
from pymongo.mongo_client import MongoClient
from pymongo import MongoClient
import certifi
import re
from flask_dance.contrib.google import make_google_blueprint, google
from oauthlib.oauth2.rfc6749.errors import TokenExpiredError

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")
CORS(app)

# 設定mongoDB
uri = "mongodb+srv://Barry:3Pj8xaolGJdW4XjO@professor-x-db.lx4sy0k.mongodb.net/?retryWrites=true&w=majority&appName=professor-x-DB"
app.config["MONGO_URI"] = uri
ca = certifi.where() # 設定這個就不會出現SSL憑證錯誤
client = MongoClient(uri, tlsCAFile=ca)

# 獲取資料庫和集合
db = client['myDatabase'] 
test_collection = db['test_collection']
content_db = db["contents"]
google_db = db["google_login"]
users_db = db['users']


# 設置google login
google_bp = make_google_blueprint(
    client_id=os.getenv("client_id"),
    client_secret=os.getenv("client_secret"),
    redirect_to="index",
)
app.register_blueprint(google_bp, url_prefix="/login")


# 從環境變量中獲取 API 金鑰
load_dotenv() 
api_key = os.environ.get("OPENAI_API_KEY")
client = OpenAI(
    api_key=api_key,
)
headers = {
    "Authorization": f"Bearer {api_key}"
}


# 測試連線mongoDB
@app.route('/test_mongo_write', methods=['GET'])
def test_mongo_write():
    try:
        # 嘗試寫入一筆數據到MongoDB的"test_collection"集合中
        test_data = {"message": "Hello, MongoDB!", "timestamp": datetime.now()}
        test_collection.insert_one(test_data)
        return jsonify({"success": True, "message": "Data written to MongoDB successfully!"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/test_mongo_read', methods=['GET'])
def test_mongo_read():
    try:
        # 嘗試從MongoDB的"test_collection"集合中讀取所有數據
        data = test_collection.find()
        result = [{"message": item["message"], "timestamp": item["timestamp"]} for item in data]
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})




@app.route("/")
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
            
            # 構建要存儲的用戶信息字典，包括令牌
            user_info_to_store = {
                "google_id": google_id,  # Google ID
                "name": name,  # 使用者名稱
            }

            # 檢查數據庫是否已有該使用者
            existing_user = users_db.find_one({"google_id": google_id})
            if existing_user:
                # 如果使用者已存在，更新其資訊和令牌
                users_db.update_one({"google_id": google_id}, {"$set": user_info_to_store})
            else:
                # 如果使用者不存在，創建新使用者
                users_db.insert_one(user_info_to_store)

        else:
            return "無法獲取使用者資訊", 500
    except TokenExpiredError:
        return redirect(url_for("google.login"))  # 引導用戶重新登入
    
    return render_template('index.html', user_name=name)





# 下載 YouTube 音訊
def download_youtube_audio_as_mp3(youtube_url):
    current_time = datetime.now().strftime("%Y%m%d_%H%M%S")

    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(youtube_url, download=False)
        video_title = info.get('title', 'DownloadedAudio')[:5]  # 獲取標題的前五個字元
        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")  # 獲取當前時間戳
        # 結合影片標題的前五個字元與時間戳作為檔案名
        final_filename = f"{video_title}_{current_time}"
        ydl_opts['outtmpl'] = final_filename  # 更新選項中的檔案名模板

    # 使用更新後的選項再次建立yt_dlp實例並下載轉換
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([youtube_url])

    return segment_audio(final_filename + ".mp3", 5)  # 假設分段長度為5分鐘

# 音訊分段
def segment_audio(filename, segment_length_minutes):
    segment_length_ms = segment_length_minutes * 60 * 1000
    audio = AudioSegment.from_file(filename)
    
    segments = []
    start = 0
    part = 1
    while start < len(audio):
        end = start + segment_length_ms
        segment = audio[start:end]
        segment_filename = f"{filename[:-4]}_{str(part).zfill(2)}.mp3"
        segment.export(segment_filename, format="mp3")
        segments.append(segment_filename)  # 將檔案路徑加入列表
        start += segment_length_ms
        part += 1

    os.remove(filename)  # 在完成所有分段工作後刪除原始檔案

    return segments  # 返回分段檔案的路徑列表

# 音訊轉文字
def transcribe_audio(segment_files):
    transcriptions = []
    for filename in segment_files:
        try:
            with open(filename, "rb") as audio_file:
                transcription = client.audio.transcriptions.create(
                model="whisper-1", 
                file=audio_file,
                )
                transcriptions.append(transcription.text)
            os.remove(filename) # 刪除處理過的音訊檔案
        except FileNotFoundError:
            print(f"檔案 {filename} 不存在。")
        except Exception as e:
            print(f"處理檔案 {filename} 時發生錯誤：{e}")
    
    return " ".join(transcriptions)  # 將所有片段的轉寫結果合併


# 文字摘要
def summarize_text(text):
    response = client.chat.completions.create(
        messages=[
                {"role": "system", "content": "你是專業的重點整理專家，用淺顯易懂的語句有條理的把重點整理出來。使用繁體中文，不用簡體字。"},
                {"role": "user", "content": text}
        ],
        model="gpt-3.5-turbo",
    )
    return response.choices[0].message.content


# API
@app.route('/process_video', methods=['POST'])
def process_video():
    data = request.json
    youtube_url = data['youtubeUrl']
    segment_files = download_youtube_audio_as_mp3(youtube_url)
    transcription = transcribe_audio(segment_files).replace(" ", "\n")
    summary = summarize_text(transcription)

    # 處理重點整理換行
    summary = "\n" + summary  # 在開頭添加換行符，以處理首個條目
    summary = re.sub(r"\n(\d+\.)", r"\n\1", summary)  # 在每個數字點前加上換行符
    summary = summary.lstrip("\n")  # 移除開頭多餘的換行符

    # category_id = data.get('categoryId') # 分類
    share = data.get('share', False)  # 預設不分享
    # user_id = get_logged_in_user_id() # 獲取user_id

    content_data = {
        "user_id": "user_id", # 暫時沒有用戶ID
        "file_name": segment_files,
        "category_id": "category_id", # 暫時沒有分類ID
        "transcription": transcription,
        "summary": summary,
        "shared": share,
        "timestamp": datetime.now()
    }
    try:
        content_db.insert_one(content_data)
    except Exception as e:
        print({"success": False, "message": str(e)})

    return jsonify({'transcription': transcription, 'summary': summary})


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


if __name__ == '__main__':
    app.run(ssl_context=('cert.pem', 'key.pem')) # 開發階段生成SSL


