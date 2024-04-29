from openai import OpenAI
from dotenv import load_dotenv
import os
from concurrent.futures import ThreadPoolExecutor, as_completed



load_dotenv() 

# 使用 get_secret 函數來獲取各種配置
openai_api_key = os.getenv("OPENAI_API_KEY")

# 從環境變量中獲取 API 金鑰
client = OpenAI(
    api_key=openai_api_key,
)

def transcribe_segment(filename, index, add_timestamp):
    """處理單個音訊文件的轉寫，返回包括索引的結果"""
    response_format = "srt" if add_timestamp else "text"

    try:
        with open(filename, "rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                model="whisper-1", 
                file=audio_file,
                response_format=response_format
            )
            print(f"transcribe_segment {index}: Transcription successful.")

            return index, transcription
            
    except FileNotFoundError:
        print(f"檔案 {filename} 不存在。")
    except Exception as e:
        print(f"處理檔案 {filename} 時發生錯誤：{e}")
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
    return " ".join(filter(None, transcriptions))  # 組合所有轉寫結果，並過濾掉任何 None 值


print(transcribe_segment("test.mp3", 1, False))