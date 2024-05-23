# /professor-x/payment/routes.py
from flask import render_template, request, jsonify
from . import payment_bp
import requests
import hashlib
import datetime
from dotenv import load_dotenv
import os
import uuid
import time
import random

load_dotenv() 

# 使用 UUID 生成唯一訂單號碼
def generate_unique_trade_no():
    return str(uuid.uuid4())


@payment_bp.route('/payment', methods=['GET'])
def payment_form():
    return render_template('payment_form.html')  # 前端信用卡輸入表單頁面

@payment_bp.route('/process_payment', methods=['POST'])
def process_payment():
    token = request.form.get('token')
    
    merchant_id = "3413057"
    hash_key = os.getenv("ECPAY_HASHKEY")
    hash_iv = os.getenv("ECPAY_HASHIV")
    service_url = "https://payment.ecpay.com.tw/Cashier/AioCheckOut/V5"  # 正式環境

    merchant_trade_no = generate_unique_trade_no()  # 生成唯一的訂單號碼

    order_params = {
        "MerchantID": merchant_id,
        "MerchantTradeNo": merchant_trade_no,  # 訂單號碼
        "MerchantTradeDate": datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
        "PaymentType": "aio",
        "TotalAmount": "1", # 交易金額
        "TradeDesc": "購買 100 點（100分鐘），沒有期限，隨時在我們的服務中使用。",
        "ItemName": "點數 100點",
        "ReturnURL": "https://professor-x.lillian-ai.com/index",
        "ChoosePayment": "Credit",
        "CreditToken": token,
        "ClientBackURL": "https://professor-x.lillian-ai.com/index",
        "ItemURL": "https://professor-x.lillian-ai.com/index",
    }

    def generate_check_mac_value(params):
        sorted_params = sorted(params.items())
        encoded_str = f"HashKey={hash_key}&" + "&".join([f"{k}={v}" for k, v in sorted_params]) + f"&HashIV={hash_iv}"
        check_mac_value = hashlib.sha256(encoded_str.encode('utf-8')).hexdigest().upper()
        return check_mac_value

    order_params["CheckMacValue"] = generate_check_mac_value(order_params)

    response = requests.post(service_url, data=order_params)

    if response.status_code == 200:
        return jsonify({"success": True, "message": "交易成功"})
    else:
        return jsonify({"success": False, "message": "交易失敗"})
