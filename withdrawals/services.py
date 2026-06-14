def can_withdraw(wallet, amount):
    return wallet.balance >= amount and amount > 0


# def initiate_withdrawal(user, amount, bank_account):
#     wallet = Wallet.objects.get(user=user)

#     if not can_withdraw(wallet, amount):
#         raise ValidationError("Insufficient balance or invalid amount.")

#     # ---------------------------
#     # Connect to Paystack Transfer
#     # ---------------------------
#     url = "https://api.paystack.co/transfer"

#     payload = {
#         "source": "balance",
#         "amount": int(amount * 100),
#         "recipient": bank_account.recipient_code,
#         "reason": "Withdrawal from Voteflow",
#     }

#     headers = {
#         "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
#         "Content-Type": "application/json"
#     }

#     response = requests.post(url, headers=headers, data=json.dumps(payload))

#     if response.status_code != 200:
#         raise Exception("Transfer initiation failed")

#     # ---------------------------
#     # Record withdrawal in DB
#     # ---------------------------
#     data = response.json()
#     withdrawal = Withdrawal.objects.create(
#         user=user,
#         amount=amount,
#         reference=data["data"]["reference"],
#         status="pending"
#     )

#     # Debit user wallet
#     wallet.balance -= amount
#     wallet.save()

#     return withdrawal