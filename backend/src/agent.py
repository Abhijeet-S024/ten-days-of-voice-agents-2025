import logging
import json
import os
import asyncio
from typing import Annotated, Literal, Optional
from dataclasses import dataclass

print(" ENGLISH TUTOR ")
print("agent.py LOADED SUCCESSFULLY!")

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

CONTENT_FILE = "english_content.json"

DEFAULT_CONTENT = [
    {
        "id": "tenses",
        "title": "English Tenses",
        "summary": "English tenses describe the time of an action. The three main tenses are Past, Present, and Future, and each has four forms: Simple, Continuous, Perfect, and Perfect Continuous.",
        "sample_question": "How many main tenses are there in English, and what are they called?"
    },
    {
        "id": "parts_of_speech",
        "title": "Parts of Speech",
        "summary": "Parts of speech are the basic categories of words based on their function. The main ones are Nouns, Pronouns, Verbs, Adjectives, Adverbs, Prepositions, Conjunctions, and Interjections.",
        "sample_question": "Name any four parts of speech and give examples."
    },
    {
        "id": "articles",
        "title": "Articles",
        "summary": "Articles are words that define a noun as specific or unspecific. The definite article is 'the'. The indefinite articles are 'a' and 'an'.",
        "sample_question": "When do we use 'a' and when do we use 'an'?"
    },
    {
        "id": "voice",
        "title": "Active and Passive Voice",
        "summary": "Voice describes whether the subject performs or receives an action. In Active Voice, the subject does the action. In Passive Voice, the subject receives the action.",
        "sample_question": "Convert this sentence to passive voice: 'The teacher teaches the students.'"
    }
]


def load_content():
    """Loads English learning content"""
    try:
        path = os.path.join(os.path.dirname(__file__), CONTENT_FILE)

        if not os.path.exists(path):
            print(f" {CONTENT_FILE} not found. Generating English content...")
            with open(path, "w", encoding='utf-8') as f:
                json.dump(DEFAULT_CONTENT, f, indent=4)
            print(" English content file created successfully.")

        with open(path, "r", encoding='utf-8') as f:
            data = json.load(f)
            return data

    except Exception as e:
        print(f" Error managing content file: {e}")
        return []


COURSE_CONTENT = load_content()


@dataclass
class TutorState:
    """ Tracks the current learning context"""
    current_topic_id: str | None = None
    current_topic_data: dict | None = None
    mode: Literal["learn", "quiz", "teach_back"] = "learn"

    def set_topic(self, topic_id: str):
        topic = next((item for item in COURSE_CONTENT if item["id"] == topic_id), None)
        if topic:
            self.current_topic_id = topic_id
            self.current_topic_data = topic
            return True
        return False


@dataclass
class Userdata:
    tutor_state: TutorState
    agent_session: Optional[AgentSession] = None


@function_tool
async def select_topic(
    ctx: RunContext[Userdata],
    topic_id: Annotated[str, Field(description="The ID of the English topic to study (e.g., 'tenses', 'articles', 'parts_of_speech')")]
) -> str:
    """ Selects a topic to study from the available English lessons."""
    state = ctx.userdata.tutor_state
    success = state.set_topic(topic_id.lower())

    if success:
        return f"Topic set to {state.current_topic_data['title']}. Ask the user if they want to 'Learn', be 'Quizzed', or 'Teach it back'."
    else:
        available = ", ".join([t["id"] for t in COURSE_CONTENT])
        return f"Topic not found. Available topics are: {available}"


@function_tool
async def set_learning_mode(
    ctx: RunContext[Userdata],
    mode: Annotated[str, Field(description="The mode to switch to: 'learn', 'quiz', or 'teach_back'")]
) -> str:
    """ Switches the interaction mode and updates the agent's voice/persona."""

    state = ctx.userdata.tutor_state
    state.mode = mode.lower()

    agent_session = ctx.userdata.agent_session

    if agent_session:
        if state.mode == "learn":
            agent_session.tts.update_options(voice="en-US-matthew", style="Promo")
            instruction = f"Mode: LEARN. Explain: {state.current_topic_data['summary']}"

        elif state.mode == "quiz":
            agent_session.tts.update_options(voice="en-US-alicia", style="Conversational")
            instruction = f"Mode: QUIZ. Ask this question: {state.current_topic_data['sample_question']}"

        elif state.mode == "teach_back":
            agent_session.tts.update_options(voice="en-US-ken", style="Promo")
            instruction = "Mode: TEACH_BACK. Ask the user to explain the concept to you."

        else:
            return "Invalid mode."

    else:
        instruction = "Voice switch failed (Session not found)."

    print(f" SWITCHING MODE -> {state.mode.upper()}")
    return f"Switched to {state.mode} mode. {instruction}"


@function_tool
async def evaluate_teaching(
    ctx: RunContext[Userdata],
    user_explanation: Annotated[str, Field(description="The explanation given by the user during teach-back")]
) -> str:
    """ Evaluates user's explanation in Teach-Back Mode """
    print(f" EVALUATING EXPLANATION: {user_explanation}")
    return "Analyze the user's explanation. Give them a score out of 10 on clarity and correctness. Correct any mistakes and offer a better explanation if needed."


class TutorAgent(Agent):
    def __init__(self):

        topic_list = ", ".join([f"{t['id']} ({t['title']})" for t in COURSE_CONTENT])

        super().__init__(
            instructions=f"""
            You are an English Tutor. Your goal is to help users learn English grammar, vocabulary, and writing skills.

            **AVAILABLE TOPICS:** {topic_list}

            **YOU HAVE 3 MODES:**
            1. **LEARN Mode (Matthew):** Explain the English topic in simple terms.
            2. **QUIZ Mode (Alicia):** Ask the user the topic's quiz question.
            3. **TEACH_BACK Mode (Ken):** Ask the user to explain the topic in their own words.

            **BEHAVIOR:**
            - Start by asking what English topic they want to study today.
            - Use the `set_learning_mode` tool when the user requests Learn / Quiz / Teach.
            - In Teach-Back mode, listen to their explanation and then use `evaluate_teaching` to give feedback.
            """,
            tools=[select_topic, set_learning_mode, evaluate_teaching],
        )


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}

    print(" STARTING ENGLISH TUTOR SESSION")
    print(f" Loaded {len(COURSE_CONTENT)} topics from English Knowledge Base")

    userdata = Userdata(tutor_state=TutorState())

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=murf.TTS(
            voice="en-US-matthew",
            style="Promo",
            text_pacing=True,
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        userdata=userdata,
    )

    userdata.agent_session = session

    await session.start(
        agent=TutorAgent(),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC()
        ),
    )

    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))

