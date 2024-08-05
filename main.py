import json
import logging
from io import BytesIO
from ssl import SSLError
from operator import itemgetter
import threading
import asyncio
from sqlitedict import SqliteDict

import requests
import websocket
from dotenv import dotenv_values
from nextcord.ext import commands
from nextcord.webhook import SyncWebhook
from nextcord import Intents, Message, File, Embed

logging.basicConfig()

intents = Intents.default()
intents.message_content = True
intents.typing = True

MEOWER_TOKEN, DSC_TOKEN, CHANNEL, WEBHOOK, MEOWER_USR, DSC_PING, DSC_USR = itemgetter(
    "MEOWER_TOKEN",
    "DSC_TOKEN",
    "CHANNEL",
    "WEBHOOK",
    "MEOWER_USR",
    "DSC_PING",
    "DSC_USR",
)(dotenv_values())
CHANNEL = int(CHANNEL)

bot = commands.Bot(command_prefix="$", intents=intents)
db = SqliteDict("posts.db")


@bot.event
async def on_typing(_channel, user, _when):
    if user == DSC_USR:
        h = requests.post(
            "https://api.meower.org/home/typing", headers={"Token": MEOWER_TOKEN}
        )


@bot.event
async def on_message(message: Message):
    if message.webhook_id or message.channel.id != CHANNEL:
        return

    reply_to = [db[message.reference.message_id]] if message.reference else []
    attachments = []

    for a in message.attachments:
        fh = BytesIO(await a.read())
        files = {"file": (a.filename, fh, a.content_type)}
        resp = requests.post(
            "https://uploads.meower.org/attachments",
            files=files,
            headers={
                "Authorization": MEOWER_TOKEN,
            },
        )
        if resp.status_code != 200:
            print(resp.status_code, resp.text)
            print("could not send attachment ", a.filename)
            continue
        attachments.append(resp.json()["id"])

    resp = requests.post(
        "https://api.meower.org/home",
        json={
            "attachments": attachments,
            "content": message.content,
            "reply_to": reply_to,
        },
        headers={"Token": MEOWER_TOKEN, "Content-Type": "application/json"},
    )
    if resp.status_code != 200:
        print("could not send")
        print(resp.status_code, resp.text)


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
        reply_id = {v: k for k, v in db.items()}[replies[0]["_id"]]
        old_msg = h.fetch_message(reply_id)
        embed = Embed(description=f"{replies[0]['p']} [⤴]({old_msg.jump_url})")
        embed.set_author(
            name=f"@{old_msg.author.name}",
            url=f"https://app.meower.org/users/{old_msg.author.name}",
            icon_url=old_msg.author.display_avatar.url,
        )
        params["embed"] = embed

    message = h.send(content.replace(MEOWER_USR, DSC_USR), **params)
    db[message.id] = packet["val"]["_id"]
    db.commit()


async def edit_webhook_post(packet, delete):
    message_id = {v: k for k, v in db.items()}[
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
