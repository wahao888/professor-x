# paypal_integration.py
import paypalrestsdk
from flask import jsonify, request, redirect, url_for
import logging

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
    
# 創建訂閱產品
def create_product():
    product = paypalrestsdk.Product({
        "name": "Professor X 訂閱服務",
        "description": "每月音訊轉譯服務訂閱",
        "type": "SERVICE",
        "category": "SOFTWARE"
    })

    if product.create():
        print("Product Created Successfully")
        return product.id
    else:
        print(product.error)
        return None
    

# 創建訂閱計劃
def create_plan(product_id, amount):
    billing_plan = paypalrestsdk.BillingPlan({
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
                    "value": amount,
                    "currency_code": "USD"
                }
            }
        }],
        "payment_preferences": {
            "auto_bill_outstanding": True,
            "setup_fee": {
                "value": amount,
                "currency_code": "USD"
            },
            "setup_fee_failure_action": "CONTINUE",
            "payment_failure_threshold": 3
        }
    })

    if billing_plan.create():
        print("Plan Created Successfully")
        return billing_plan.id
    else:
        print(billing_plan.error)
        return None

# 創建訂閱實例
def create_subscription(plan_id, start_time, customer_email, given_name, surname):
    subscription = paypalrestsdk.Subscription({
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
    })

    if subscription.create():
        logging.info("Subscription Created Successfully")
        print("Subscription Created Successfully")
        return subscription
    else:
        print(subscription.error)
        return None



