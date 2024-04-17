from google.cloud import storage

# 初始化 Storage 客戶端
client = storage.Client()

# 列出所有存儲桶
buckets = list(client.list_buckets())
print(buckets)
