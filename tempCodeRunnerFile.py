    print("收到請求")
    data = request.json
    print(f"請求數據：{data}")
    youtube_url = data['youtubeUrl']
    segment_files = "download_youtube_audio_as_mp3(youtube_url)"
    transcription = "transcribe_audio(segment_files)"
    summary = "summarize_text(transcription)"
    return jsonify({'transcription': transcription, 'summary': summary})