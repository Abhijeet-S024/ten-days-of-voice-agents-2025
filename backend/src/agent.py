# pirate_rpg_advanced.py
"""
Day 8 – Voice Game Master (Pirate Treasure Hunt Adventure)
Fully upgraded version based on your engine:
⚓ Persistent world state
⚓ Inventory, journal, choices, scene tracking
⚓ start_adventure / player_action / show_journal / restart_adventure tools
⚓ Multi-path branching story progression
"""

import os, uuid, asyncio, logging, json
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Annotated

from dotenv import load_dotenv
from pydantic import Field

from livekit.agents import (
    Agent, AgentSession, JobContext,
    JobProcess, RoomInputOptions,
    WorkerOptions, cli, function_tool, RunContext
)

from livekit.plugins import murf, silero, google, deepgram, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel

load_dotenv(".env.local")
logger = logging.getLogger("pirate_rpg")
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler())



WORLD = {
    "beach": {
        "title": "The Tide of Fate",
        "desc": (
            "Waves crash silver under moonlight. Your shipwreck rests behind you—splintered, gone.\n"
            "A pirate cutlass lies half-buried in sand, beside a bottle sealed with a crimson wax skull.\n"
            "Far away, a lantern flickers atop a cliffside fort — rumored to guard the Skullfire Treasure."
        ),
        "choices": {
            "take_sword": {
                "desc": "Pick up the cutlass.",
                "result_scene": "clifftop_path",
                "effects": {"add_inventory": "cutlass", "add_journal": "Claimed a pirate cutlass from the wreck."}
            },
            "open_bottle": {
                "desc": "Unseal the wax-marked bottle.",
                "result_scene": "bottle_map",
            },
            "head_to_fort": {
                "desc": "Walk directly toward the fort lights.",
                "result_scene": "fort_gate",
            },
        }
    },

    "bottle_map": {
        "title": "The Message Inside",
        "desc": (
            "Inside the bottle is a torn map fragment reading:\n"
            "⚓ 'In the captain's chest — beneath the gallows bells.' ⚓\n"
            "Wind howls as if warning you. You see the fort more clearly now."
        ),
        "choices": {
            "pocket_map": {
                "desc": "Keep the map fragment with you.",
                "result_scene": "clifftop_path",
                "effects": {"add_journal": "Found map: 'beneath the gallows bells'."}
            },
            "discard_message": {
                "desc": "Toss it aside and trust luck alone.",
                "result_scene": "beach",
            }
        }
    },

    "clifftop_path": {
        "title": "Path of Rum & Ruin",
        "desc": (
            "You climb the cliff path—boots slipping over wet stone.\n"
            "Above, cannonfire echoes from the fort. A rusty gate creaks, open just enough for one soul."
        ),
        "choices": {
            "enter_gate": {
                "desc": "Slip through the crooked gate.",
                "result_scene": "fort_courtyard",
            },
            "search_area": {
                "desc": "Search around the path for supplies.",
                "result_scene": "stash_find",
            },
            "retreat": {
                "desc": "Return to the beach.",
                "result_scene": "beach",
            }
        }
    },

    "stash_find": {
        "title": "Smuggler's Stash",
        "desc": (
            "Hidden behind rocks you find a leather pouch containing dried rum-berries\n"
            "and a **silver compass** engraved with a Kraken sigil—it hums faintly."
        ),
        "choices": {
            "take_compass": {
                "desc": "Pocket the humming compass.",
                "result_scene": "clifftop_path",
                "effects": {"add_inventory": "Kraken Compass", "add_journal": "Recovered a Kraken-marked compass."}
            },
            "eat_berries": {
                "desc": "Taste a rum-berry for courage.",
                "result_scene": "vision_event",
                "effects": {"add_journal": "Rum-berry vision triggered — fate altered?"}
            }
        }
    },

    "vision_event": {
        "title": "Rum-Berry Visions",
        "desc": (
            "You see a ghostly captain dangling from gallows bells whispering:\n"
            "'The treasure sings only to those who bleed saltwater...'\n"
            "When vision clears, you're back on the cliff path — heart racing."
        ),
        "choices": {
            "move_to_fort": {
                "desc": "Advance toward the fort.",
                "result_scene": "fort_gate",
            },
            "rest": {
                "desc": "Steady yourself and return to beach.",
                "result_scene": "beach",
            }
        }
    },

    "fort_gate": {
        "title": "Fort Grimjaw",
        "desc": (
            "Torches burn along jagged walls. Inside — laughter, steel,\n"
            "and the faint ringing of gallows bells.\n\n"
            "Two pirates guard the gate, drunk and loud."
        ),
        "choices": {
            "sneak_in": {
                "desc": "Attempt to sneak past them.",
                "result_scene": "courtyard_shadow",
            },
            "challenge": {
                "desc": "Walk up and challenge the guards boldly.",
                "result_scene": "duel",
            },
            "bribe": {
                "desc": "Try bribing them with charm or rumor.",
                "result_scene": "bribe_pass",
                "effects": {"add_journal": "Talked your way past Grimjaw gate guards."}
            }
        }
    },

    "duel": {
        "title": "Steel at Dawn",
        "desc": (
            "Blades flash. Sparks fly. After a brutal exchange, you knock one pirate down.\n"
            "The other flees, leaving behind a brass key carved with skull-teeth."
        ),
        "choices": {
            "take_key": {
                "desc": "Take the skull-tooth key.",
                "result_scene": "fort_courtyard",
                "effects": {"add_inventory": "Skull-Tooth Key", "add_journal": "Won duel — claimed tower key."}
            },
            "leave_key": {
                "desc": "Leave it and limp onward.",
                "result_scene": "fort_courtyard",
            }
        }
    },

    "bribe_pass": {
        "title": "Smooth Sailing",
        "desc": (
            "A few clever words and a wicked grin — they step aside.\n"
            "But you sense one might betray you later for coin..."
        ),
        "choices": {
            "push_forward": {
                "desc": "Enter the fort courtyard.",
                "result_scene": "fort_courtyard",
            }
        }
    },

    "courtyard_shadow": {
        "title": "The Quiet Kill",
        "desc": (
            "You slip through shadows. Ahead lies the Captain's Chamber—\n"
            "where rumor says the Skullfire Jewel sleeps."
        ),
        "choices": {
            "enter_chamber": {
                "desc": "Push open the massive doors.",
                "result_scene": "treasure_room",
            },
            "climb_roof": {
                "desc": "Scale rope toward belltower.",
                "result_scene": "belltower",
            }
        }
    },


    "fort_courtyard": {
        "title": "Court of Rogues",
        "desc": (
            "Tables of rum, crates of powder, and at center — the Captain's Door.\n"
            "Above it hangs a great rope & gallows bell..."
        ),
        "choices": {
            "enter_chamber": {"desc": "Attempt to enter.", "result_scene": "treasure_room"},
            "climb_bell": {"desc": "Climb toward the bell — map hinted something!", "result_scene": "belltower"},
        }
    },

    "belltower": {
        "title": "Bells of Dead Men",
        "desc": (
            "Wind screams across height. Three heavy bells sway.\n"
            "Under the middle one — a chest bound in iron. Your map whispered this place..."
        ),
        "choices": {
            "unlock_chest": {
                "desc": "Use the key OR force the lock.",
                "result_scene": "Skullfire_jewel",
                "effects": {"add_inventory": "Skullfire Jewel", "add_journal": "Claimed the Skullfire Treasure!"}
            },
            "leave_it": {
                "desc": "Turn away — too cursed to touch.",
                "result_scene": "fort_courtyard",
            }
        }
    },

    "treasure_room": {
        "title": "Captain's Tomb",
        "desc": (
            "Candles burn blue. A skeletal captain sits eternal, crown cracked.\n"
            "Before him — a locket showing the fort before ruin.\n\nYou may take it... or bow and leave."
        ),
        "choices": {
            "take_locket": {
                "desc": "Claim the Captain's Locket.",
                "result_scene": "Skullfire_jewel",
                "effects": {"add_inventory": "Captain's Locket", "add_journal": "Claimed pirate captain's relic."}
            },
            "bow_and_leave": {
                "desc": "Show respect & exit.",
                "result_scene": "fort_courtyard",
            }
        }
    },

    "Skullfire_jewel": {
        "title": "THE TREASURE CLAIMED",
        "desc": (
            "Heat like wildfire fills your chest as the Jewel glows crimson.\n"
            "Some say it grants power. Others—madness.\n\nTonight, the seas remember your name."
        ),
        "choices": {
            "end_session": {"desc": "Leave the fort victorious.", "result_scene": "beach"},
            "continue_adventure": {"desc": "Seek more danger. Treasure was never enough.", "result_scene": "fort_courtyard"}
        }
    }
}



@dataclass
class Userdata:
    player_name: Optional[str] = None
    current_scene: str = "beach"
    history: List[Dict] = field(default_factory=list)
    journal: List[str] = field(default_factory=list)
    inventory: List[str] = field(default_factory=list)
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat()+"Z")


def scene(scene_key, user):
    sc = WORLD.get(scene_key)
    if not sc:
        return "Lost at sea. No path forward. What do you do?"
    msg = sc["desc"] + "\n\nChoices:\n"
    for cid,c in sc["choices"].items():
        msg+=f"– {c['desc']} (say '{cid}')\n"
    return msg+"\nWhat do you do?"

def apply_effects(effects,user):
    if not effects: return
    if "add_inventory" in effects: user.inventory.append(effects["add_inventory"])
    if "add_journal"   in effects: user.journal.append(effects["add_journal"])


@function_tool
async def start_adventure(ctx:RunContext[Userdata],name:Annotated[str,Field(description="Player name")]) -> str:
    user=ctx.userdata
    user.player_name=name
    user.current_scene="beach"
    return f" Welcome aboard, Captain {name}! Your fate begins.\n\n"+scene("beach",user)


@function_tool
async def get_scene(ctx:RunContext[Userdata]) -> str:
    return scene(ctx.userdata.current_scene,ctx.userdata)


@function_tool
async def player_action(ctx:RunContext[Userdata],action:Annotated[str,Field(description="Your move, pirate!")]) -> str:
    user=ctx.userdata
    sc=WORLD[user.current_scene]; act=action.lower().strip()
    
    # fuzzy match
    chosen=None
    for cid in sc["choices"]:
        if cid in act: chosen=cid; break

    if not chosen:
        return "The seas don't understand yer words — speak clearer!\n\n"+scene(user.current_scene,user)

    nxt=sc["choices"][chosen]["result_scene"]
    apply_effects(sc["choices"][chosen].get("effects"),user)
    user.history.append({"scene":user.current_scene,"action":chosen,"to":nxt,"time":datetime.utcnow().isoformat()})

    user.current_scene=nxt
    return scene(nxt,user)


@function_tool
async def show_journal(ctx:RunContext[Userdata]) -> str:
    u=ctx.userdata; o=f" Captain Log — {u.player_name}\nInventory:{u.inventory}\nJournal:\n"
    for j in u.journal: o+="– "+j+"\n"
    o+="\nWhat do you do?"
    return o


@function_tool
async def restart_adventure(ctx:RunContext[Userdata]) -> str:
    ctx.userdata=Userdata()
    return " The tides reset. A new hunt begins.\n\n"+scene("beach",ctx.userdata)


class PirateGM(Agent):
    def __init__(self):
        super().__init__(
            instructions="""
You are **Captain Redblade**, Game Master of the Pirate Treasure Hunt RPG.
Always respond narratively. Always end with **What do you do?**
If tools exist, call them logically.
""",
tools=[start_adventure,get_scene,player_action,show_journal,restart_adventure])


def prewarm(proc:JobProcess):
    try:proc.userdata["vad"]=silero.VAD.load()
    except:pass


async def entrypoint(ctx:JobContext):
    session=AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=murf.TTS(voice="en-US-marcus",style="Narrative",text_pacing=True),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata.get("vad"),
        userdata=Userdata()
    )
    await session.start(agent=PirateGM(),room=ctx.room,room_input_options=RoomInputOptions(noise_cancellation=noise_cancellation.BVC()))
    await ctx.connect()


if __name__=="__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint,prewarm_fnc=prewarm))
