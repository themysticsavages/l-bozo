from typing import TypedDict
import json
from random import randint
from io import BytesIO
from pathlib import Path

import websocket
from dotenv import dotenv_values
import requests

from objection_engine import render_comment_list
from objection_engine.beans.comment import Comment

v = dotenv_values()
USERNAME, PASSWORD = v["USERNAME"], v["PASSWORD"]
MAX_POSTS = 50


class SimplifiedMsg(TypedDict):
    content: str
    username: str
    mention: str
    image: str | None


token = requests.post(
    "https://api.meower.org/auth/login",
    json={"username": USERNAME, "password": PASSWORD},
).json()["token"]


def post_msg(msg, reply_to: str = None):
    reply_to = [reply_to] if reply_to else []
    return requests.post(
        "https://api.meower.org/home",
        json={"content": msg, "reply_to": reply_to},
        headers={"Token": token, "Content-Type": "application/json"},
    ).json()


def do_the_thing(count: int):
    pages = max(1, round(count + 2 / 25))
    _count = 0
    posts = []

    def make_post(post: dict[str]) -> SimplifiedMsg:
        mention = None
        if post["reply_to"]:
            mention = post["reply_to"][0]["author"]["_id"]
        attachments = post.get("attachments")

        image = None
        if attachments:
            f: str = attachments[0]["filename"]
            if f.split(".")[-1] in ["png", "jpg", "jpeg", "webp"]:
                resp = requests.get(
                    f"https://uploads.meower.org/attachments/{attachments[0]['id']}"
                )
                with open("attachments/" + attachments[0]["filename"], "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024):
                        if chunk:
                            f.write(chunk)
                image = attachments[0]["filename"]

        return {
            "content": post["p"] if post["p"] != "" else "<no message>",
            "username": post["author"]["_id"],
            "mention": "@" + mention + " " if mention else "",
            "image": ("attachments/" + image) if image else None,
        }

    for i in range(pages, pages + 1):
        resp = requests.get(
            "https://api.meower.org/home",
            params={"page": i},
        ).json()["autoget"]
        for post in resp:
            if _count == count + 2:
                break
            posts.append(make_post(post))
            _count += 1

    posts: list[SimplifiedMsg] = list(reversed(posts))[: len(posts) - 2]

    return [
        Comment(
            user_name=post["username"],
            text_content=f"{post['mention']}{post['content']}",
            evidence_path=post["image"],
        )
        for post in posts
    ]


def on_message(_, message):
    try:
        msg = json.loads(message)
        if msg["cmd"] == "post":
            post = msg["val"]["p"]
            if not post.startswith("@objection"):
                return
            if post.split()[1].lower() == "help":
                post_msg(
                    f"use `@objection render <number of posts before the command>`\nmaximum of {MAX_POSTS} post{'s' if MAX_POSTS > 1 else ''}",
                    msg["val"]["_id"],
                )
                return
            if post.split()[1].lower() != "render":
                return

            count = post.split()[-1]
            try:
                count = int(count)
            except ValueError:
                return

            if count > 50:
                post_msg(
                    f"sorry bro only {MAX_POSTS} post{'s' if MAX_POSTS > 1 else ''} at a time i run on a potato",
                    msg["val"]["_id"],
                )
                return
            if count == 0:
                post_msg(f"shut up", msg["val"]["_id"])
                return

            idk = "DDDDDD" if randint(1, 10) == 1 else ""
            msg_id = post_msg(
                f"Objectioning {count} post{'s' if count > 1 else ''} (i'll ping you when i'm done{' :D' + idk if randint(1, 4) == 1 else ''})",
                msg["val"]["_id"],
            )["_id"]

            render_comment_list(do_the_thing(count))

            print("done")
            requests.delete(
                "https://api.meower.org/posts",
                params={"id": msg_id},
                headers={"Token": token, "Content-Type": "application/json"},
            )

            fh = BytesIO(open("output.mp4", "rb").read())
            resp = requests.post(
                "https://uploads.meower.org/attachments",
                files={"file": ("output.mp4", fh, "video/mp4")},
                headers={
                    "Authorization": token,
                },
            )
            file_ = resp.json()["id"]
            requests.post(
                "https://api.meower.org/home",
                json={
                    "content": f"here's the thing you wanted",
                    "attachments": [file_],
                    "reply_to": [msg["val"]["_id"]],
                },
                headers={"Token": token, "Content-Type": "application/json"},
            ).json()
            for f in Path("attachments/").glob("*"):
                if f.name == ".gitkeep":
                    f.unlink()
    except json.decoder.JSONDecodeError:
        pass


def on_open(socket):
    socket.send(
        json.dumps({"cmd": "authpswd", "val": {"username": USERNAME, "pswd": token}})
    )


if __name__ == "__main__":
    sock = websocket.WebSocketApp(
        f"wss://server.meower.org?v=1&token={token}",
        on_message=on_message,
        on_open=on_open,
    )
    sock.run_forever()
