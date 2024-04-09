from flask import Flask, request, jsonify, render_template
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


app = Flask(__name__)
CORS(app)

# 設定mongoDB
uri = "mongodb+srv://Barry:3Pj8xaolGJdW4XjO@professor-x-db.lx4sy0k.mongodb.net/?retryWrites=true&w=majority&appName=professor-x-DB"
app.config["MONGO_URI"] = uri
ca = certifi.where() # 設定這個就不會出現SSL憑證錯誤
client = MongoClient(uri, tlsCAFile=ca)

# 獲取資料庫和集合
db = client['myDatabase'] 
test_collection = db['test_collection']

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



load_dotenv() 

# 從環境變量中獲取 API 金鑰
api_key = os.environ.get("OPENAI_API_KEY")
client = OpenAI(
    api_key=api_key,
)
headers = {
    "Authorization": f"Bearer {api_key}"
}

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

@app.route('/')
def home():
    return render_template('index.html')

# API
@app.route('/process_video', methods=['POST'])
def process_video():
    data = request.json
    youtube_url = data['youtubeUrl']
    segment_files = download_youtube_audio_as_mp3(youtube_url)
    transcription = transcribe_audio(segment_files)
    summary = summarize_text(transcription)

    return jsonify({'transcription': transcription, 'summary': summary})


if __name__ == '__main__':
    app.run(debug = True)
