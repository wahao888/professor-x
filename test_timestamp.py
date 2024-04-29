from openai import OpenAI
from dotenv import load_dotenv
import os


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
            # 根據 add_timestamp 的值決定返回的內容
            if response_format == "srt":
                return index, transcription
            else:
                return index, transcription
            
    except FileNotFoundError:
        print(f"檔案 {filename} 不存在。")
    except Exception as e:
        print(f"處理檔案 {filename} 時發生錯誤：{e}")
    return index, ""

print(transcribe_segment("test.mp3", 1, False))