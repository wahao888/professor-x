from flask import Flask, request, jsonify, render_template
import yt_dlp
from pydub import AudioSegment
import os
from dotenv import load_dotenv
from datetime import datetime
from openai import OpenAI
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

load_dotenv() 

client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
)

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
