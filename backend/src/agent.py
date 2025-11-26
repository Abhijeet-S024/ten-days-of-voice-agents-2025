import logging
import json
import os
import asyncio
from datetime import datetime
from typing import Annotated, Optional
from dataclasses import dataclass, asdict


print(" AI SDR AGENT — SUJUGO EDITION ")
print(" agent.py LOADED SUCCESSFULLY!")

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

FAQ_FILE = "sujugo_faq.json"
LEADS_FILE = "leads_db.json"

DEFAULT_FAQ = {
    "company": "Sujugo",
    "description": "Sujugo is a virtual and hybrid event platform that helps enterprises host webinars, internal events, conferences, and large-scale hybrid experiences with backstage production, branding, engagement tools, and analytics.",
    "faqs": [
        {
            "question": "What does Sujugo do?",
            "answer": "Sujugo helps companies host virtual and hybrid events with backstage production tools, speaker management, branded virtual stages, engagement features, and real-time analytics."
        },
        {
            "question": "Who is Sujugo for?",
            "answer": "Sujugo is designed for enterprises, marketing teams, HR teams, event agencies, and organizations looking to host webinars, product launches, conferences, and hybrid events."
        },
        {
            "question": "Do you support hybrid events?",
            "answer": "Yes, Sujugo fully supports hybrid events combining in-person and virtual attendees with unified production tools."
        },
        {
            "question": "Do you provide analytics?",
            "answer": "Yes, Sujugo includes attendee engagement analytics, session performance data, and event-level reporting."
        },
        {
            "question": "What features do you offer?",
            "answer": "Sujugo offers registration, ticketing, backstage mode, speaker management, virtual stages, breakout rooms, networking tools, engagement widgets, and detailed analytics."
        },
        {
            "question": "How does pricing work?",
            "answer": "Sujugo uses custom pricing based on event size and requirements. The team provides a quote after understanding your event needs."
        },
        {
            "question": "Do you integrate with CRMs?",
            "answer": "Yes, Sujugo integrates with Salesforce, HubSpot, Marketo, and other enterprise CRMs."
        },
        {
            "question": "Is there a free tier?",
            "answer": "Sujugo does not offer a free tier, but provides demo access and pilot programs upon request."
        }
    ]
}


def load_knowledge_base():
    try:
        path = os.path.join(os.path.dirname(__file__), FAQ_FILE)
        if not os.path.exists(path):
            with open(path, "w", encoding='utf-8') as f:
                json.dump(DEFAULT_FAQ, f, indent=4)

        with open(path, "r", encoding='utf-8') as f:
            return json.dumps(json.load(f))

    except Exception as e:
        print(f" Error loading FAQ: {e}")
        return ""


STORE_FAQ_TEXT = load_knowledge_base()


@dataclass
class LeadProfile:
    name: str | None = None
    company: str | None = None
    email: str | None = None
    role: str | None = None
    event_type: str | None = None
    attendee_size: str | None = None
    timeline: str | None = None

    def is_qualified(self):
        return all([self.name, self.email, self.event_type])


@dataclass
class Userdata:
    lead_profile: LeadProfile


@function_tool
async def update_lead_profile(
    ctx: RunContext[Userdata],
    name: Optional[str] = None,
    company: Optional[str] = None,
    email: Optional[str] = None,
    role: Optional[str] = None,
    event_type: Optional[str] = None,
    attendee_size: Optional[str] = None,
    timeline: Optional[str] = None,
) -> str:

    profile = ctx.userdata.lead_profile

    if name: profile.name = name
    if company: profile.company = company
    if email: profile.email = email
    if role: profile.role = role
    if event_type: profile.event_type = event_type
    if attendee_size: profile.attendee_size = attendee_size
    if timeline: profile.timeline = timeline

    print(f" UPDATING LEAD: {profile}")
    return "Lead profile updated. Continue the conversation."


@function_tool
async def submit_lead_and_end(ctx: RunContext[Userdata]) -> str:

    profile = ctx.userdata.lead_profile
    db_path = os.path.join(os.path.dirname(__file__), LEADS_FILE)

    entry = asdict(profile)
    entry["timestamp"] = datetime.now().isoformat()

    existing_data = []
    if os.path.exists(db_path):
        try:
            with open(db_path, "r") as f:
                existing_data = json.load(f)
        except:
            pass

    existing_data.append(entry)

    with open(db_path, "w") as f:
        json.dump(existing_data, f, indent=4)

    print(f" LEAD SAVED TO {LEADS_FILE}")

    return (
        f"Lead saved. Summarize the call: "
        f"Thank you {profile.name}. I have your details for your {profile.event_type} event. "
        f"We will contact you shortly at {profile.email}. Goodbye!"
    )


class SDRAgent(Agent):
    def __init__(self):
        super().__init__(
            instructions=f"""
            You are **Zara**, a warm and professional Sales Development Representative (SDR)
            for **Sujugo**, a virtual + hybrid event platform.

            -----------------------------
             SUJUGO KNOWLEDGE BASE
            -----------------------------
            {STORE_FAQ_TEXT}

            -----------------------------
             YOUR TASKS
            -----------------------------
            - Greet the visitor warmly.
            - Understand what kind of event they want to run.
            - Answer all product/feature/pricing questions using ONLY the FAQ.
            - Collect lead details naturally:
              • Name  
              • Company  
              • Email  
              • Role  
              • Event Type (webinar, hybrid event, conference)
              • Attendee Size  
              • Timeline  

            - Whenever the user provides a detail, call update_lead_profile.
            - When the user says “that’s all”, “thank you”, “bye”, etc. → call submit_lead_and_end.

            -----------------------------
             RULES
            -----------------------------
            - Do NOT make up answers or hallucinate.
            - Keep responses simple, friendly, and focused.
            - Avoid asking too many questions at once.
            """,
            tools=[update_lead_profile, submit_lead_and_end],
        )


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}

    print(" STARTING SUJUGO SDR SESSION ")

    userdata = Userdata(lead_profile=LeadProfile())

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=murf.TTS(
            voice="en-US-natalie",
            style="Promo",
            text_pacing=True,
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        userdata=userdata,
    )

    await session.start(
        agent=SDRAgent(),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC()
        ),
    )

    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
