import json
import logging
from io import BytesIO
from ssl import SSLError
from operator import itemgetter
import threading
import asyncio

import requests
import websocket
from dotenv import load_dotenv
from nextcord.ext import commands
from nextcord.webhook import SyncWebhook
from nextcord import Intents, Message, File

logging.basicConfig()

intents = Intents.default()
intents.message_content = True

MEOWER_TOKEN, DSC_TOKEN, CHANNEL, WEBHOOK, MEOWER_USR, DSC_USR = itemgetter(
    "MEOWER_TOKEN", "DSC_TOKEN", "CHANNEL", "WEBHOOK", "MEOWER_USR", "DSC_USR"
)(load_dotenv())
CHANNEL = int(CHANNEL)

bot = commands.Bot(command_prefix="$", intents=intents)
d2m = {}


@bot.event
async def on_message(message: Message):
    reply_to = []
    if message.webhook_id or message.channel.id != CHANNEL:
        return
    if message.reference:
        reply_to.append(d2m[message.reference.message_id])

    with requests.get(
        "https://api.meower.org/home",
        json={"attachments": [], "content": message.content, "reply_to": reply_to},
        headers={"Token": MEOWER_TOKEN, "Content-Type": "application/json"},
    ) as resp:
        if resp.status != 200:
            print("could not send")


def get_attachment(a):
    url = f"https://uploads.meower.org/attachments/{a['id']}/{a['filename']}"
    return File(BytesIO(requests.get(url).content), filename=a["filename"])


async def send_webhook_post(packet):
    h = SyncWebhook.from_url(WEBHOOK, bot_token=DSC_TOKEN)
    content = packet["val"]["p"]
    attachments = packet["val"]["attachments"]

    params = dict(
        files=[get_attachment(a) for a in attachments],
        username=packet["val"]["u"],
        avatar_url=f"https://uploads.meower.org/icons/{packet['val']['author']['avatar']}",
        wait=True,
    )

    replies = packet["val"]["reply_to"]
    if replies:
        reply_id = {v: k for k, v in d2m.items()}[replies[0]["_id"]]
        old_msg = h.fetch_message(reply_id)
        content = (
            f"> @{old_msg.author.name} {replies[0]['p']} {old_msg.jump_url}\n{content}"
        )

    message = h.send(content.replace(MEOWER_USR, DSC_USR), **params)
    d2m[message.id] = packet["val"]["_id"]


async def edit_webhook_post(packet, delete):
    message_id = {v: k for k, v in d2m.items()}[
        packet["val"]["_id"] if not delete else packet["val"]["post_id"]
    ]

    channel = bot.get_channel(CHANNEL)
    message = await channel.fetch_message(message_id)

    if delete:
        await message.delete()
    else:
        message = message.id
        wb = SyncWebhook.from_url(WEBHOOK)
        wb.edit_message(message, content=packet["val"]["p"])


async def listen_for_messages():
    sock = websocket.WebSocket()
    sock.connect("wss://server.meower.org?v=1")
    while True:
        try:
            message: dict = json.loads(sock.recv())
            cmd = message.get("cmd", "")
            if cmd == "post":
                asyncio.run_coroutine_threadsafe(send_webhook_post(message), bot.loop)
            elif cmd == "update_post":
                asyncio.run_coroutine_threadsafe(
                    edit_webhook_post(message, False), bot.loop
                )
            elif cmd == "delete_post":
                asyncio.run_coroutine_threadsafe(
                    edit_webhook_post(message, True), bot.loop
                )
        except SSLError:
            pass


threading.Thread(target=asyncio.run, args=(listen_for_messages(),)).start()

bot.run(DSC_TOKEN)
