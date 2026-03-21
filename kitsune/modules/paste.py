
from __future__ import annotations

from ..core.loader import KitsuneModule, command
from ..core.security import OWNER

class PasteModule(KitsuneModule):
    name        = "paste"
    description = "Публикация текста на Telegraph"
    author      = "Yushi"
    version     = "1.0"

    strings_ru = {
        "uploading":  "⏳ Загружаю на Telegraph...",
        "done":       "📄 <a href=\"{url}\">Открыть на Telegraph</a>",
        "no_text":    "❌ Нет текста для публикации.\nОтветь на сообщение или напиши: <code>.paste текст</code>",
        "error":      "❌ Ошибка: <code>{err}</code>",
    }

    @command("paste", required=OWNER)
    async def paste_cmd(self, event) -> None:
        text = self.get_args(event) or None

        if not text:
            reply = await event.message.get_reply_message()
            if reply and reply.text:
                text = reply.text
            elif reply and reply.message:
                text = reply.message

        if not text:
            await event.reply(self.strings("no_text"), parse_mode="html")
            return

        m = await event.reply(self.strings("uploading"), parse_mode="html")
        try:
            url = await self._publish(text)
            await m.edit(self.strings("done").format(url=url), parse_mode="html", link_preview=False)
        except Exception as exc:
            await m.edit(self.strings("error").format(err=str(exc)), parse_mode="html")

    async def _publish(self, text: str) -> str:
        import httpx

        nodes = []
        for paragraph in text.split("\n\n"):
            paragraph = paragraph.strip()
            if paragraph:
                nodes.append({
                    "tag": "p",
                    "children": [paragraph],
                })
            else:
                nodes.append({"tag": "br"})

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.telegra.ph/createPage",
                json={
                    "access_token": await self._get_token(client),
                    "title": "Kitsune Paste",
                    "content": nodes,
                    "return_content": False,
                },
            )
            data = resp.json()
            if not data.get("ok"):
                raise RuntimeError(data.get("error", "Unknown error"))
            return data["result"]["url"]

    async def _get_token(self, client) -> str:
        token = self.db.get("kitsune.paste", "telegraph_token", None)
        if token:
            return str(token)

        resp = await client.post(
            "https://api.telegra.ph/createAccount",
            json={
                "short_name": "Kitsune",
                "author_name": "Kitsune Userbot",
                "author_url": "https://github.com/KitsuneX-dev/Kitsune",
            },
        )
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError("Failed to create Telegraph account")
        token = data["result"]["access_token"]
        await self.db.set("kitsune.paste", "telegraph_token", token)
        return token
