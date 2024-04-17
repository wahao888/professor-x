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
from google.cloud import secretmanager, storage

app = Flask(__name__)
CORS(app)

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

# 設置google login
google_bp = make_google_blueprint(
    client_id=google_client_id,
    client_secret=google_client_secret,
    redirect_to="index",
)
app.register_blueprint(google_bp, url_prefix="/login")

# 從環境變量中獲取 API 金鑰
client = OpenAI(
    api_key=openai_api_key,
)



@app.route("/")
def welcome():
    return render_template('welcome.html')

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
            
            # 構建要存儲的用戶信息字典，包括令牌
            user_info_to_store = {
                "google_id": google_id,  # Google ID
                "name": name,  # 使用者名稱
            }

            # 檢查數據庫是否已有該使用者
            existing_user = users_db.find_one({"google_id": google_id})
            if existing_user:
                # 如果使用者已存在
                users_db.update_one({"google_id": google_id}, {"$set": user_info_to_store})
            else:
                # 如果使用者不存在，創建新使用者
                users_db.insert_one(user_info_to_store)

            # 取得用戶點數
            user_points = 0
            user_data = users_db.find_one({"google_id": google_id})
            user_points = round(user_data.get('points', 0), 2)

            session['google_id'] = google_id
            session['name'] = name
            session['user_points'] = user_points
            print("session資訊：",session['google_id'], session['name'], session['user_points'])

        else:
            return "無法獲取使用者資訊", 500
    except TokenExpiredError:
        return redirect(url_for("google.login"))  # 引導用戶重新登入
    
    return render_template('index.html', user_name=name, user_points=user_points)




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
            duration = info.get('duration', 0)  # 獲取影片時長（秒）
            token_per_second = 0.0167  # 每秒0.00167個令牌
            estimated_tokens =  round(duration * token_per_second, 2)
        return jsonify({"success": True, "duration": duration, "estimatedTokens": estimated_tokens})
    except Exception as e:
        print("錯誤訊息:", str(e))
        return jsonify({"success": False, "message": "請輸入正確的Youtube網址"}), 500




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
        video_title = info.get('title', 'DownloadedAudio') # 獲取標題的前10個字元
        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")  # 獲取當前時間戳
        # 結合影片標題的前五個字元與時間戳作為檔案名
        final_filename = f"/tmp/{video_title}_{current_time}"
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

def transcribe_segment(filename, index):
    """處理單個音訊文件的轉寫，返回包括索引的結果"""
    try:
        with open(filename, "rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                model="whisper-1", 
                file=audio_file,
            )
            return index, transcription.text
    except FileNotFoundError:
        print(f"檔案 {filename} 不存在。")
    except Exception as e:
        print(f"處理檔案 {filename} 時發生錯誤：{e}")
    finally:
        os.remove(filename)  # 確保即使出現錯誤也刪除處理過的音訊檔案
    return index, ""

def transcribe_audio(segment_files):
    """並行處理所有音訊分段的轉寫，確保按原始順序組合結果"""
    transcriptions = [None] * len(segment_files)  # 初始化結果列表，大小與分段數相同
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(transcribe_segment, filename, i) for i, filename in enumerate(segment_files)]
        for future in as_completed(futures):
            index, transcription_result = future.result()
            transcriptions[index] = transcription_result  # 按索引放置轉寫結果

    return " ".join(filter(None, transcriptions))  # 組合所有轉寫結果，並過濾掉任何 None 值



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

    # 針對該用戶檢查URL是否已經處理過
    google_id = session.get('google_id')  # 獲取使用者的Google ID
    existing_content = content_db.find_one({"url": youtube_url, "google_id": google_id})
    if existing_content:
        # 如果URL已經存在，返回提示
        return jsonify({"success": False, "message": "已經處理過囉！"})

    # 全面檢查URL是否已經處理過
    checkall_existing_content = content_db.find_one({"url": youtube_url})
    if checkall_existing_content:
        # 如果找到相關記錄，則直接回傳存在的資料
        return jsonify({
            "success": True,
            "transcription": checkall_existing_content["transcription"],
            "summary": checkall_existing_content["summary"],
            "file_name": checkall_existing_content["file_name"]
        })

    # 語音轉文字
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
    file_name = segment_files[0][5:15]

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
    user_points = session.get('user_points', 0)  # 如果沒有找到，預設為 0
    name = session.get('name')
    return render_template('payment.html', user_name=name, user_points=user_points)

# 初始化 PayPal
paypal_integration.init_paypal(paypal_client_id, paypal_secret)

@app.route('/pay/<amount>')
def pay(amount):
    try:
        payment_url = paypal_integration.create_payment(app, amount)  # 接受金額作為參數
        if payment_url:
            return redirect(payment_url)
        else:
            return 'Unable to create payment'
    except Exception as e:
        return str(e)

def calculate_points_based_on_amount(amount):
    # 定義每個計劃的點數
    plans = {
        '10': 1200, # 假設 $10 購買 1200 點
        '20': 3000, # 假設 $20 購買 3000 點
        '30': 6000, # 假設 $30 購買 6000 點
    }
    return plans.get(amount, 0)  # 返回相對應的點數，如果金額不匹配則


@app.route('/payment_completed')
def payment_completed():
    payment_id = request.args.get('paymentId')
    payer_id = request.args.get('PayerID')
    success, message = paypal_integration.execute_payment(payment_id, payer_id)
    if success:
        # 取得購買的點數數量
        amount = request.args.get('amount')
        # 計算點數數量，這需要您根據實際方案自行計算
        points = calculate_points_based_on_amount(amount)
        google_id = session.get('google_id')
        if google_id:
            # 更新資料庫中的點數數量
            users_db.update_one({"google_id": google_id}, {"$inc": {"points": points}})
            flash(f'Payment successful! You now have {points} additional points.', 'success')
        else:
            flash('You need to log in to receive points.', 'error')
    else:
        flash(message, 'error')

    return redirect(url_for('index'))

@app.route('/payment_cancelled')
def payment_cancelled():
    flash("Payment cancelled by the user")  # Store the cancellation message
    return redirect(url_for('index'))  # Redirect to the homepage




if __name__ == '__main__':
    app.run(ssl_context=('cert.pem', 'key.pem')) # 開發階段生成SSL
    # app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))



# 開發階段不使用HTTPS，終端機輸入：
# export OAUTHLIB_INSECURE_TRANSPORT=1 
