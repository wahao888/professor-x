# paypal_integration.py
import paypalrestsdk
from flask import jsonify, request, redirect, url_for

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
