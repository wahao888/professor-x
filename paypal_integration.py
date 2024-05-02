# paypal_integration.py
import paypalrestsdk
from flask import jsonify, request, redirect, url_for
import logging
import requests
from requests.auth import HTTPBasicAuth
import uuid

# 設定日誌級別和格式
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    # filename='/var/log/myapp.log',
    filename='myapp.log',  # 指定日誌文件的路徑
    filemode='a'  # 附加模式
)

# 初始化 PayPal SDK
def init_paypal(client_id, client_secret):
    paypalrestsdk.configure({
        "mode": "sandbox",  # 或 "live" 如果你準備上線
        "client_id": client_id,
        "client_secret": client_secret
    })



# 創建支付並返回支付 URL
def create_payment(app, amount, currency='USD'):
    payment = paypalrestsdk.Payment({
        "intent": "sale",
        "payer": {
            "payment_method": "paypal"
        },
        "redirect_urls": {
            "return_url": url_for('payment_completed', _external=True, _scheme='https'),
            "cancel_url": url_for('payment_cancelled', _external=True, _scheme='https'),
        },
        "transactions": [{
            "item_list": {
                "items": [{
                    "name": "item",
                    "sku": "item",
                    "price": amount,
                    "currency": currency,
                    "quantity": 1
                }]
            },
            "amount": {
                "total": amount,
                "currency": currency
            },
            "description": "This is the payment transaction description."
        }]
    })

    if payment.create():
        print("Payment created successfully")
        for link in payment.links:
            if link.rel == "approval_url":
                # 返回 PayPal 進行支付的 URL
                return link.href
    else:
        print(payment.error)
        return None

# 執行支付
def execute_payment(payment_id, payer_id):
    payment = paypalrestsdk.Payment.find(payment_id)

    if payment.execute({"payer_id": payer_id}):
        print("Payment execute successfully")
        return True, "Payment completed"
    else:
        print(payment.error)  # Error handling
        return False, "Payment execution failed"




# =====以下為訂閱相關功能=====
# 獲取訪問令牌
def get_access_token(client_id, client_secret):
    url = "https://api-m.sandbox.paypal.com/v1/oauth2/token"  # Use sandbox URL for testing
    headers = {
        "Accept": "application/json",
        "Accept-Language": "en_US",
    }
    body = {
        "grant_type": "client_credentials"
    }
    response = requests.post(url, headers=headers, data=body, auth=HTTPBasicAuth(client_id, client_secret))
    if response.status_code == 200:
        logging.info("Access Token Retrieved Successfully")
        return response.json()['access_token']  # Returns the access token
    else:
        logging.error("Error retrieving access token")
        return None  # Handle errors appropriately


# 創建訂閱產品
def create_product(access_token):
    url = "https://api-m.sandbox.paypal.com/v1/catalogs/products"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
        "PayPal-Request-Id": str(uuid.uuid4()) # Replace this with a unique ID.
    }
    payload = {
        "name": "Video Streaming Service",
        "description": "A video streaming service",
        "type": "SERVICE",
        "category": "SOFTWARE",
        "image_url": "https://example.com/streaming.jpg",
        "home_url": "https://example.com/home"
    }
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 201:
        logging.info("Product Created Successfully")
        return response.json()['id']  # This will return the product ID and other details
    else:
        logging.error("Error creating product")
        return response.text  # Handle errors
    

# 創建訂閱計劃
def create_plan(access_token, product_id, amount):
    url = "https://api-m.sandbox.paypal.com/v1/billing/plans"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
        "PayPal-Request-Id": str(uuid.uuid4())
    }
    payload = {
        "product_id": product_id,
        "name": "基本月付方案",
        "description": "每月1200點（20小時）音訊轉譯。",
        "billing_cycles": [{
            "frequency": {
                "interval_unit": "MONTH",
                "interval_count": 1
            },
            "tenure_type": "REGULAR",
            "sequence": 1,
            "total_cycles": 12,
            "pricing_scheme": {
                "fixed_price": {
                    "value": str(amount),
                    "currency_code": "USD"
                }
            }
        }],
        "payment_preferences": {
            "auto_bill_outstanding": True,
            "setup_fee": {
                "value": str(amount),
                "currency_code": "USD"
            },
            "setup_fee_failure_action": "CONTINUE",
            "payment_failure_threshold": 3
        }
    }

    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 201:
        logging.info("Plan Created Successfully")
        return response.json()['id']
    else:
        logging.error("Error creating plan")
        return response.text

# 創建訂閱實例
def create_subscription(access_token, plan_id, start_time, customer_email, given_name, surname):
    url = "https://api-m.sandbox.paypal.com/v1/billing/subscriptions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
        "PayPal-Request-Id": str(uuid.uuid4())  # Ensure this is unique for each request
    }
    payload = {
        "plan_id": plan_id,
        "start_time": start_time,
        "subscriber": {
            "name": {
                "given_name": given_name,
                "surname": surname
            },
            "email_address": customer_email
        },
        "application_context": {
            "brand_name": "Professor X",
            "locale": "zh-TW",
            "shipping_preference": "NO_SHIPPING",
            "user_action": "SUBSCRIBE_NOW",
            "payment_method": {
                "payer_selected": "PAYPAL",
                "payee_preferred": "IMMEDIATE_PAYMENT_REQUIRED"
            }
        }
    }

    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 201:
        logging.info("Subscription Created Successfully")
        return response.json()  # This should return the subscription details
    else:
        logging.error(f"Error creating subscription: {response.text}")
        return None



