import logging
import os
import sqlite3
from datetime import datetime
from typing import Annotated, Optional
from dataclasses import dataclass

print("  PUNJAB NATIONAL BANK FRAUD AGENT INITIALIZED")
print(" TASK FLOW: Verify Identity → Check Transaction → Update DB (SQLite)")

from dotenv import load_dotenv
from pydantic import Field
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    RoomInputOptions,
    WorkerOptions,
    cli,
    function_tool,
    RunContext,
)

from livekit.plugins import murf, silero, google, deepgram, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel

logger = logging.getLogger("agent")
load_dotenv(".env.local")

DB_FILE = "fraud_db.sqlite"


@dataclass
class FraudCase:
    userName: str
    securityIdentifier: str
    cardEnding: str
    transactionName: str
    transactionAmount: str
    transactionTime: str
    transactionSource: str
    case_status: str = "pending_review"
    notes: str = ""


def get_db_path():
    return os.path.join(os.path.dirname(__file__), DB_FILE)


def get_conn():
    path = get_db_path()
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def seed_database():
    """Create DB & add sample customer records on first run."""
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS fraud_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            userName TEXT NOT NULL,
            securityIdentifier TEXT,
            cardEnding TEXT,
            transactionName TEXT,
            transactionAmount TEXT,
            transactionTime TEXT,
            transactionSource TEXT,
            case_status TEXT DEFAULT 'pending_review',
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
        """
    )

    cur.execute("SELECT COUNT(1) FROM fraud_cases")
    if cur.fetchone()[0] == 0:
        sample_data = [
            (
                "Jatin", "12345", "4242",
                "Replit Industry", "$450.00", "2:30 AM EST", "alibaba.com",
                "pending_review", "Flagged: High value at unusual platform."
            ),
            (
                "Sarah", "99887", "1199",
                "Unknown Crypto Exchange", "$2,100.00", "4:15 AM PST", "online_transfer",
                "pending_review", "Flagged: Suspicious cross-border crypto deposit."
            ),
            (
                "Rohan", "56473", "8890",
                "EBay Motors", "$1,750.00", "11:50 PM IST", "ebay.in",
                "pending_review", "Flagged: First-time high amount transaction."
            ),
            (
                "Priya", "77124", "6602",
                "Amazon Gift Cards", "$520.00", "8:10 AM IST", "amazon.com",
                "pending_review", "Flagged: Gift card transactions often used in scam extortion."
            ),
            (
                "Michael", "44219", "3508",
                "Forex Trading Platform", "$6,900.00", "1:35 AM GMT", "globalforex.net",
                "pending_review", "Flagged: Unverified offshore forex trading activity."
            )
        ]

        cur.executemany(
            """
            INSERT INTO fraud_cases (
                userName, securityIdentifier, cardEnding, transactionName,
                transactionAmount, transactionTime, transactionSource,
                case_status, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            sample_data,
        )
        conn.commit()
        print(" ✔ SQLite database created & sample customer data added.")

    conn.close()

seed_database()


@dataclass
class Userdata:
    active_case: Optional[FraudCase] = None


@function_tool
async def lookup_customer(
    ctx: RunContext[Userdata],
    name: Annotated[str, Field(description="Customer name for fraud lookup")],
) -> str:
    print(f" Searching Customer: {name}")
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM fraud_cases WHERE LOWER(userName) = LOWER(?) LIMIT 1", (name,)
        )
        row = cur.fetchone()
        conn.close()

        if not row:
            return "No matching customer found in PNB fraud watchlist. Please confirm the name."

        record = dict(row)
        ctx.userdata.active_case = FraudCase(
            userName=record["userName"],
            securityIdentifier=record["securityIdentifier"],
            cardEnding=record["cardEnding"],
            transactionName=record["transactionName"],
            transactionAmount=record["transactionAmount"],
            transactionTime=record["transactionTime"],
            transactionSource=record["transactionSource"],
            case_status=record["case_status"],
            notes=record["notes"],
        )

        return (
            f"Match found in system.\n"
            f"Customer → {record['userName']}\n"
            f"Expected Security ID → {record['securityIdentifier']}\n"
            f"Flagged Transaction → {record['transactionAmount']} at {record['transactionName']} ({record['transactionSource']})\n"
            f"Request the customer to verify their Security Identifier now."
        )

    except Exception as e:
        return f"Database lookup error: {str(e)}"


@function_tool
async def resolve_fraud_case(
    ctx: RunContext[Userdata],
    status: Annotated[str, Field(description="confirmed_safe or confirmed_fraud")],
    notes: Annotated[str, Field(description="Reason / user confirmation")],
) -> str:

    if not ctx.userdata.active_case:
        return "⚠ No customer case active. Lookup first."

    case = ctx.userdata.active_case
    case.case_status = status
    case.notes = notes

    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE fraud_cases
            SET case_status=?, notes=?, updated_at=datetime('now')
            WHERE userName=?
            """,
            (case.case_status, case.notes, case.userName),
        )
        conn.commit()

        cur.execute("SELECT * FROM fraud_cases WHERE userName=?", (case.userName,))
        updated_row = dict(cur.fetchone())
        conn.close()

        print(f" CASE UPDATED: {case.userName} => {status}")

        if status == "confirmed_fraud":
            return (
                f"FRAUD CONFIRMED.\n"
                f"Card ending {case.cardEnding} has been BLOCKED.\n"
                f"A new card will be issued within 5 working days.\n"
                f"Database Updated → {updated_row['updated_at']}"
            )
        else:
            return (
                f" Transaction marked SAFE. No further action taken.\n"
                f"Database Updated → {updated_row['updated_at']}"
            )

    except Exception as e:
        return f"Database update failed: {e}"


class FraudAgent(Agent):
    def __init__(self):
        super().__init__(
            instructions="""
            You are 'Alex', Senior Fraud Detection Officer at Punjab National Bank (PNB).

            Begin every conversation with:
            "Namaste, welcome to Punjab National Bank. May I please have your first name for verification?"

            Workflow to follow STRICTLY:

            1. Greet customer & ask for FIRST NAME.
            2. Immediately call → lookup_customer(name)
            3. Ask customer for their SECURITY IDENTIFIER.
            4. If correct → continue. If incorrect → end call politely.
            5. Explain flagged transaction clearly.
            6. Ask: "Did you authorize this transaction?"
               - YES → resolve_fraud_case('confirmed_safe')
               - NO  → resolve_fraud_case('confirmed_fraud')
            7. Confirm final resolution & close the session professionally.
            """,
            tools=[lookup_customer, resolve_fraud_case],
        )


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    print("  Initiating PNB Fraud Monitoring Session")

    userdata = Userdata()

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=murf.TTS(voice="en-US-marcus", style="Conversational", text_pacing=True),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        userdata=userdata,
    )

    await session.start(
        agent=FraudAgent(),
        room=ctx.room,
        room_input_options=RoomInputOptions(noise_cancellation=noise_cancellation.BVC()),
    )

    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
