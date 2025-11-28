# grocery_agent_smartbazar.py
"""
Day 7 – SMARTBAZAR Grocery Voice Agent (SQLite) – Indian Market Edition 
► Live conversational shopping assistant
► Indian grocery catalog with recipes + cart + auto-order-status simulation
► More personality, more fun, more real-shop feel 
"""

import json, logging, os, sqlite3, uuid, asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Annotated
from dotenv import load_dotenv
from pydantic import Field

from livekit.agents import (
    Agent, AgentSession, JobContext, JobProcess,
    RoomInputOptions, WorkerOptions, cli, function_tool, RunContext
)

from livekit.plugins import murf, silero, google, deepgram, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel


DB_FILE = "smartbazar_orders.sqlite"
logger = logging.getLogger("smartbazar")
load_dotenv(".env.local")

def get_db_path():
    return os.path.join(os.path.dirname(__file__), DB_FILE)

def get_conn():
    conn = sqlite3.connect(get_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def seed_database():
    conn = get_conn(); cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS catalog (
            id TEXT PRIMARY KEY,
            name TEXT,
            category TEXT,
            price REAL,
            brand TEXT,
            size TEXT,
            units TEXT,
            tags TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            timestamp TEXT,
            total REAL,
            customer_name TEXT,
            address TEXT,
            status TEXT DEFAULT 'received',
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT,
            item_id TEXT,
            name TEXT,
            unit_price REAL,
            quantity INTEGER,
            notes TEXT
        )
    """)

    cur.execute("SELECT COUNT(1) FROM catalog")
    if cur.fetchone()[0] == 0:

        ### More items + wider Indian feel + useful combinations
        catalog = [
            ("milk-amul-1l","Amul Taaza Milk","Dairy",72,"Amul","1L","pack",json.dumps(["breakfast","chai","essential"])),
            ("atta-5kg","Aashirvaad Atta","Staples",245,"Aashirvaad","5kg","bag",json.dumps(["flour","roti"])),
            ("rice-1kg","India Gate Basmati Rice","Staples",160,"India Gate","1kg","pack",json.dumps(["rice"])),
            ("dal-toor","Tata Sampann Toor Dal","Staples",180,"Tata","1kg","pack",json.dumps(["protein"])),
            ("maggi","Maggi Masala 2-Min","Instant",14,"Nestle","70g","pack",json.dumps(["snack","quick"])),
            ("oil-fortune","Fortune Sunflower Oil","Staples",150,"Fortune","1L","bottle",json.dumps(["cooking"])),
            ("biscuits-parle","Parle-G Biscuits","Snacks",10,"Parle-G","70g","pack",json.dumps(["chai partner"])),
            ("tea-taj","Taj Mahal Tea","Beverages",150,"Brooke Bond","250g","box",json.dumps(["chai"])),
            ("sugar-1kg","Madhur Sugar","Staples",60,"Madhur","1kg","pack",json.dumps(["sweet"])),
            ("chips-kurkure","Kurkure Masala Munch","Snacks",20,"Kurkure","50g","pack",json.dumps(["spicy"])),
            ("poha-1kg","Indori Poha","Breakfast",90,"Local","1kg","pack",json.dumps(["poha","morning"])),
            ("onion-1kg","Fresh Onions","Veggies",55,"","1kg","kg",json.dumps(["sabzi"])),
            ("tomato-1kg","Fresh Tomatoes","Veggies",60,"","1kg","kg",json.dumps(["sabzi"])),
            ("ginger-100g","Fresh Ginger","Veggies",20,"","100g","g",json.dumps(["chai"])),
        ]
        
        cur.executemany("INSERT INTO catalog VALUES (?,?,?,?,?,?,?,?)", catalog)
        conn.commit()
        print(" Grocery store database successfully stocked!")

seed_database()



@dataclass
class CartItem:
    item_id: str
    name: str
    unit_price: float
    quantity: int = 1
    notes: str = ""

@dataclass
class Userdata:
    cart: List[CartItem] = field(default_factory=list)
    customer_name: Optional[str] = None


def _db_get_item(item_id: str):
    conn=get_conn();cur=conn.cursor()
    cur.execute("SELECT * FROM catalog WHERE id=?",(item_id,))
    row=cur.fetchone(); conn.close()
    return dict(row) if row else None

def cart_total(cart): return sum(i.unit_price*i.quantity for i in cart)


@function_tool
async def add_item(ctx:RunContext[Userdata], item_id:str, quantity:int=1):
    item=_db_get_item(item_id)
    if not item: return "Item doesn't exist — try 'maggi', 'atta', 'oil', 'milk'."
    for i in ctx.userdata.cart:
        if i.item_id==item_id: i.quantity+=quantity; break
    else:
        ctx.userdata.cart.append(CartItem(item_id,item["name"],item["price"],quantity))
    return f" Added ✓ {item['name']} x{quantity} → Cart total now ₹{cart_total(ctx.userdata.cart):.2f}"


@function_tool
async def show_cart(ctx:RunContext[Userdata]):
    if not ctx.userdata.cart: return "Cart is empty 🛒"
    lines=[f"• {i.quantity}× {i.name} (₹{i.unit_price})" for i in ctx.userdata.cart]
    return "Your Cart:\n"+"\n".join(lines)+f"\nTotal: ₹{cart_total(ctx.userdata.cart):.2f}"


@function_tool
async def checkout(ctx:RunContext[Userdata], name:str, address:str):
    if not ctx.userdata.cart: return "Nothing in cart!"
    order_id=str(uuid.uuid4())[:6]
    insert_order(order_id,name,address,ctx.userdata.cart)
    ctx.userdata.cart=[]; ctx.userdata.customer_name=name
    asyncio.create_task(simulate_status(order_id))
    return f" Order placed! ID: {order_id}\n Packing & shipping soon!"



STATUS = ["received","packed","shipped","out_for_delivery","delivered"]

def insert_order(order_id,name,address,items):
    conn=get_conn();cur=conn.cursor()
    total=cart_total(items); now=datetime.utcnow().isoformat()
    cur.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?)",(order_id,now,total,name,address,"received",now))
    for i in items:
        cur.execute("INSERT INTO order_items(order_id,item_id,name,unit_price,quantity) VALUES (?,?,?,?,?)",
                    (order_id,i.item_id,i.name,i.unit_price,i.quantity))
    conn.commit(); conn.close()


async def simulate_status(order_id):
    for s in STATUS[1:]:
        await asyncio.sleep(5)
        conn=get_conn();cur=conn.cursor()
        cur.execute("UPDATE orders SET status=?,updated_at=datetime('now') WHERE order_id=?", (s,order_id))
        conn.commit();conn.close()
        print(f" Order {order_id} → {s}")
    print(f" Order {order_id} delivered!")


class GroceryAgent(Agent):
    def __init__(self):
        super().__init__(
            instructions="""
You are **Ramesh**, the friendly SmartBazar Grocery AI Shopkeeper.
Speak like a helpful Indian vendor — warm, funny, welcoming 🌶😄  

Opening Tone:
 "Namaste ji! Welcome to SmartBazar — fresh items, fair prices!
What can I pack for you today?"

Capabilities:
• Suggest groceries + show item list if needed
• Add items to cart, remove, update, show final total
• Recommend combos like Chai Set (Milk+Tea+Sugar), Poha Breakfast pack
• Recipes for chai, maggi, poha
• Place online order with delivery tracking updates every 5 seconds 🚚

Be friendly, crack small desi-style lines like:
"Maggi aur chai — perfect rainy day combo!"  

""",
            tools=[add_item, show_cart, checkout],
        )


def prewarm(proc:JobProcess):
    try: proc.userdata["vad"]=silero.VAD.load()
    except: pass


async def entrypoint(ctx:JobContext):
    session=AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=murf.TTS(voice="en-US-marcus"),  
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata.get("vad"),
        userdata=Userdata(),
    )

    await session.start(agent=GroceryAgent(), room=ctx.room,
        room_input_options=RoomInputOptions(noise_cancellation=noise_cancellation.BVC()))
    await ctx.connect()


if __name__=="__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
