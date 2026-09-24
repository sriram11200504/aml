"""
Seed 200 accounts and demo customers into the fake bank database.
Idempotent – safe to run multiple times.
"""
import logging
import random
from datetime import datetime

from sqlalchemy import select
from .database import AsyncSessionLocal
from .models import Account

logger = logging.getLogger(__name__)

INDIA_NAMES = [
    "Ravi Kumar", "Priya Sharma", "Ankit Patel", "Sunita Devi", "Rajesh Singh",
    "Deepa Nair", "Vikram Reddy", "Pooja Gupta", "Arjun Mehta", "Kavita Joshi",
    "Suresh Iyer", "Meena Pillai", "Arun Krishnan", "Lakshmi Rao", "Mohan Das",
    "Geeta Agarwal", "Ramesh Yadav", "Sita Pandey", "Vinod Tiwari", "Asha Verma",
    "Nitin Saxena", "Ritu Mishra", "Ajay Chauhan", "Pooja Srivastava", "Dinesh Kapoor",
    "Seema Bhatt", "Manoj Kumar", "Usha Rani", "Santosh Dubey", "Rekha Jain",
    "Pawan Goel", "Nita Shah", "Vikas Malhotra", "Preeti Chopra", "Anil Bose",
    "Sudha Menon", "Rakesh Nanda", "Sunila Bhatia", "Hemant Soni", "Kiran Babu",
]

UK_NAMES = [
    "James Smith", "Emily Johnson", "Oliver Brown", "Charlotte Davis", "Harry Wilson",
    "Sophia Taylor", "George Anderson", "Isabella Thomas", "Jack Jackson", "Mia White",
    "William Harris", "Amelia Martin", "Noah Thompson", "Isla Garcia", "Liam Martinez",
    "Grace Robinson", "Benjamin Lewis", "Hannah Walker", "Lucas Hall", "Lily Allen",
]

UAE_NAMES = [
    "Mohammed Al Rashid", "Fatima Al Zaabi", "Ahmed Al Mansoori", "Aisha Al Hamdan",
    "Khalid Al Maktoum", "Sara Al Suwaidi", "Omar Al Shamsi", "Noura Al Kaabi",
    "Yusuf Al Dhaheri", "Mariam Al Falasi",
]

LOCATIONS = ["India"] * 150 + ["UK"] * 30 + ["UAE"] * 20

CURRENCIES = {
    "India": "Indian rupee",
    "UK": "British pound",
    "UAE": "UAE dirham",
}

# Named demo customers (always present, used in the frontend "choose customer" list)
DEMO_CUSTOMERS = [
    {"account_id": 8724731955, "holder_name": "Ravi Kumar", "currency": "Indian rupee", "bank_location": "India", "balance": 5000000.0},
    {"account_id": 2769355426, "holder_name": "Priya Sharma", "currency": "Indian rupee", "bank_location": "India", "balance": 1000000.0},
    {"account_id": 5513892047, "holder_name": "Ankit Patel", "currency": "Indian rupee", "bank_location": "India", "balance": 2000000.0},
    {"account_id": 3380124867, "holder_name": "James Smith", "currency": "British pound", "bank_location": "UK", "balance": 500000.0},
    {"account_id": 9901234567, "holder_name": "Mohammed Al Rashid", "currency": "UAE dirham", "bank_location": "UAE", "balance": 3000000.0},
]


def _rand_account_id(existing: set) -> int:
    while True:
        aid = random.randint(1000000000, 9999999999)
        if aid not in existing:
            existing.add(aid)
            return aid


async def seed_database():
    async with AsyncSessionLocal() as session:
        # Check if already seeded
        result = await session.execute(select(Account).limit(1))
        if result.scalar_one_or_none():
            logger.info("Database already seeded, skipping")
            return

        existing_ids: set = set()
        accounts = []

        # Add demo customers first
        for c in DEMO_CUSTOMERS:
            existing_ids.add(c["account_id"])
            accounts.append(Account(**c, status="active"))

        # Generate 195 additional accounts
        india_names = INDIA_NAMES.copy() * 10
        uk_names = UK_NAMES.copy() * 10
        uae_names = UAE_NAMES.copy() * 10
        random.shuffle(india_names)

        for i in range(195):
            loc = random.choice(LOCATIONS)
            if loc == "India":
                name = india_names[i % len(india_names)]
            elif loc == "UK":
                name = uk_names[i % len(uk_names)]
            else:
                name = uae_names[i % len(uae_names)]

            currency = CURRENCIES[loc]
            aid = _rand_account_id(existing_ids)
            balance = random.uniform(50000, 2000000)
            accounts.append(
                Account(
                    account_id=aid,
                    holder_name=name,
                    currency=currency,
                    bank_location=loc,
                    balance=round(balance, 2),
                    status="active",
                )
            )

        session.add_all(accounts)
        await session.commit()
        logger.info("Seeded %d accounts", len(accounts))
