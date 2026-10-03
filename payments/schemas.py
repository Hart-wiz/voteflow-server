from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from ninja import ModelSchema, Schema, Field
from .models import Transaction, Wallet

# -------------------------------------------------------------------
# Transaction Schemas
# -------------------------------------------------------------------

class TransactionSchema(ModelSchema):
    date: datetime = Field(..., alias="created_at")

    class Meta:
        model = Transaction
        fields = ("id", "description", "amount", "status", "type")

# -------------------------------------------------------------------
# Wallet Schemas
# -------------------------------------------------------------------

class WalletSchema(Schema):
    availableBalance: Decimal
    pendingEarnings: Decimal
    lifetimeEarnings: Decimal
    transactions: List[TransactionSchema]

class WithdrawSchema(Schema):
    amount: Decimal
    bank_code: str
    account_number: str

# -------------------------------------------------------------------
# Payment Schemas
# -------------------------------------------------------------------

class PayForVoteSchema(Schema):
    email: str
    amount: Decimal
    metadata: Optional[dict] = {}

class PayForVoteResponseSchema(Schema):
    authorization_url: str
