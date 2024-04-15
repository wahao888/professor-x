#app.py

from flask import Flask, request, jsonify, render_template, redirect, url_for, session
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
from concurrent.futures import ThreadPoolExecutor, as_completed
import paypal_integration  # 引用另外創建的 PayPal 集成模組

app = Flask(__name__)
load_dotenv() 
app.secret_key = os.getenv("FLASK_SECRET_KEY")
CORS(app)

# 設定mongoDB
uri = os.getenv("MongoDB_url")
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

api_key = os.environ.get("OPENAI_API_KEY")
client = OpenAI(
    api_key=api_key,
)
headers = {
    "Authorization": f"Bearer {api_key}"
}


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

            session['google_id'] = google_id

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
        video_title = info.get('title', 'DownloadedAudio')[:10]  # 獲取標題的前10個字元
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
        segment_filename = f"{filename[:-4]}_{str(part).zfill(2)}.mp3" # [:-4]移除檔案擴展名
        segment.export(segment_filename, format="mp3")
        segments.append(segment_filename)  # 將檔案路徑加入列表
        start += segment_length_ms
        part += 1

    os.remove(filename)  # 在完成所有分段工作後刪除原始檔案

    return segments  # 返回分段檔案的路徑列表

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

def transcribe_segment(filename):
    """處理單個音訊文件的轉寫"""
    try:
        with open(filename, "rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                model="whisper-1", 
                file=audio_file,
            )
            return transcription.text
    except FileNotFoundError:
        print(f"檔案 {filename} 不存在。")
    except Exception as e:
        print(f"處理檔案 {filename} 時發生錯誤：{e}")
    finally:
        os.remove(filename) # 確保即使出現錯誤也刪除處理過的音訊檔案
    return ""

def transcribe_audio(segment_files):
    """並行處理所有音訊分段的轉寫"""
    transcriptions = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        # 將每個音訊文件的處理任務提交給ThreadPoolExecutor
        future_to_filename = {executor.submit(transcribe_segment, filename): filename for filename in segment_files}
        
        for future in as_completed(future_to_filename):
            transcription_result = future.result()
            if transcription_result:
                transcriptions.append(transcription_result)

    return " ".join(transcriptions)





# 文字摘要
def summarize_text(text):
    response = client.chat.completions.create(
        messages=[
                {"role": "system", "content": "你是專業的重點整理專家，用淺顯易懂的語句有條理的把重點整理出來。根據文本的語言輸出，如果是中文則只使用繁體中文字，不要用簡體字。"},
                {"role": "user", "content": text}
        ],
        model="gpt-3.5-turbo",
    )
    print(f'summarize_text: {response.usage.prompt_tokens} prompt tokens used.')

    return response.choices[0].message.content


# API
@app.route('/process_video', methods=['POST'])
def process_video():
    data = request.json
    youtube_url = data['youtubeUrl']

    # 檢查URL是否已經處理過
    google_id = session.get('google_id')  # 獲取使用者的Google ID
    existing_content = content_db.find_one({"url": youtube_url, "google_id": google_id})
    if existing_content:
        # 如果URL已經存在，返回提示
        return jsonify({"success": False, "message": "已經處理過囉！"})

    segment_files = download_youtube_audio_as_mp3(youtube_url)
    transcription = transcribe_audio(segment_files).replace(" ", "\n")
    summary = summarize_text(transcription)

    # 處理重點整理換行
    summary = "\n" + summary  # 在開頭添加換行符，以處理首個條目
    summary = re.sub(r"\n(\d+\.)", r"\n\1", summary)  # 在每個數字點前加上換行符
    summary = summary.lstrip("\n")  # 移除開頭多餘的換行符

    # category_id = data.get('categoryId') # 分類
    share = data.get('share', False)  # 預設不分享
    google_id = session.get('google_id') # 獲取使用者的Google ID
    file_name = segment_files[0][:10]

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
    except Exception as e:
        print({"success": False, "message": str(e)})

    return jsonify({
    'success': True,
    'transcription': transcription,
    'summary': summary,
    'file_name': file_name  
})

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
        return jsonify({"success": False, "message": "Content not found."}), 404


# 頁面加載時取得用戶標籤
@app.route('/get_user_contents', methods=['GET'])
def get_user_contents():
    google_id = session.get('google_id')
    if not google_id:
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



# 支付頁面
@app.route('/payment')
def payment():
    return render_template('payment.html')

# 初始化 PayPal
paypal_client_id = os.getenv("paypal_client_id")
paypal_secret = os.getenv("paypal_secret")
paypal_integration.init_paypal(paypal_client_id, paypal_secret)

@app.route('/pay')
def pay():
    payment_url = paypal_integration.create_payment(app, '5.00') # 設定支付金額為 5.00 美元
    if payment_url:
        return redirect(payment_url)
    else:
        return 'Unable to create payment'

@app.route('/payment_completed')
def payment_completed():
    payment_id = request.args.get('paymentId')
    payer_id = request.args.get('PayerID')
    success, message = paypal_integration.execute_payment(payment_id, payer_id)
    flash(message)  # Store the message to be shown on the next page
    return redirect(url_for('index'))  # Redirect to the homepage

@app.route('/payment_cancelled')
def payment_cancelled():
    flash("Payment cancelled by the user")  # Store the cancellation message
    return redirect(url_for('index'))  # Redirect to the homepage




if __name__ == '__main__':
    app.run(ssl_context=('cert.pem', 'key.pem')) # 開發階段生成SSL
    # app.run(ssl_context='adhoc')



# 開發階段不使用HTTPS，終端機輸入：
# export OAUTHLIB_INSECURE_TRANSPORT=1 
