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

