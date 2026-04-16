from __future__ import annotations

import asyncio
import logging
import typing

from ..core.loader import KitsuneModule, command, ConfigValue, ModuleConfig
from ..core.security import OWNER
from ..utils import escape_html
from ..validators import String, Choice

logger = logging.getLogger(__name__)

_WTTR_URL    = "https://wttr.in/{city}?format=j1"
_WTTR_URL_V2 = "https://v2.wttr.in/{city}?format=j1"

_WIND_DIRS = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]

_CONDITION_CODES: dict[int, str] = {
    113: "☀️ Ясно", 116: "⛅ Переменная облачность", 119: "☁️ Пасмурно",
    122: "☁️ Сплошная облачность", 143: "🌫 Туман", 176: "🌦 Местами дождь",
    179: "🌨 Местами снег", 182: "🌧 Мокрый снег", 185: "🌧 Морось",
    200: "⛈ Гроза", 227: "🌨 Метель", 230: "❄️ Сильная метель",
    248: "🌫 Туман", 260: "🌫 Ледяной туман", 263: "🌦 Лёгкий дождь",
    266: "🌧 Морось", 281: "🌧 Ледяная морось", 284: "🌧 Ледяная морось",
    293: "🌦 Лёгкий дождь", 296: "🌧 Дождь", 299: "🌧 Умеренный дождь",
    302: "🌧 Дождь", 305: "🌧 Сильный дождь", 308: "🌧 Очень сильный дождь",
    311: "🌧 Ледяной дождь", 314: "🌧 Ледяной дождь", 317: "🌧 Мокрый снег",
    320: "🌨 Мокрый снег", 323: "🌨 Лёгкий снег", 326: "🌨 Снег",
    329: "❄️ Умеренный снег", 332: "❄️ Снег", 335: "❄️ Сильный снег",
    338: "❄️ Очень сильный снег", 350: "🌧 Ледяной дождь",
    353: "🌦 Лёгкий дождь", 356: "🌧 Дождь", 359: "🌧 Ливень",
    362: "🌨 Мокрый снег", 365: "🌨 Мокрый снег", 368: "🌨 Лёгкий снег",
    371: "❄️ Снегопад", 374: "🌧 Ледяной дождь", 377: "🌧 Ледяной дождь",
    386: "⛈ Гроза с лёгким дождём", 389: "⛈ Гроза с дождём",
    392: "⛈ Гроза со снегом", 395: "⛈ Гроза с сильным снегом",
}

def _wind_direction(degrees: int) -> str:
    idx = round(degrees / 22.5) % 16
    return _WIND_DIRS[idx]

def _c_to_f(c: float) -> float:
    return round(c * 9 / 5 + 32, 1)

def _kmh_to_ms(kmh: float) -> float:
    return round(kmh / 3.6, 1)

def _parse_weather(data: dict, unit: str) -> str:
    current = data["current_condition"][0]
    nearest = data.get("nearest_area", [{}])[0]

    city_name = ""
    area_name = nearest.get("areaName", [{}])[0].get("value", "")
    country = nearest.get("country", [{}])[0].get("value", "")
    if area_name and country:
        city_name = f"{area_name}, {country}"
    elif area_name:
        city_name = area_name

    temp_c = float(current["temp_C"])
    feels_c = float(current["FeelsLikeC"])

    if unit == "F":
        temp_str = f"{_c_to_f(temp_c)}°F (ощущается {_c_to_f(feels_c)}°F)"
    else:
        temp_str = f"{temp_c:+.0f}°C (ощущается {feels_c:+.0f}°C)"

    humidity = current["humidity"]
    wind_kmh = float(current["windspeedKmph"])
    wind_dir_deg = int(current["winddirDegree"])
    wind_dir = _wind_direction(wind_dir_deg)
    wind_ms = _kmh_to_ms(wind_kmh)

    visibility = current["visibility"]
    pressure = current.get("pressure", "—")

    code = int(current["weatherCode"])
    condition = _CONDITION_CODES.get(code, current.get("weatherDesc", [{}])[0].get("value", "—"))

    weather_day = data.get("weather", [])
    forecast_lines = []
    for day_data in weather_day[:3]:
        date = day_data["date"]
        max_c = float(day_data["maxtempC"])
        min_c = float(day_data["mintempC"])
        hourly = day_data.get("hourly", [])
        day_code = int(hourly[4]["weatherCode"]) if len(hourly) > 4 else code
        day_condition = _CONDITION_CODES.get(day_code, "—")

        if unit == "F":
            temp_range = f"{_c_to_f(min_c)}…{_c_to_f(max_c)}°F"
        else:
            temp_range = f"{min_c:+.0f}…{max_c:+.0f}°C"

        forecast_lines.append(f"  <code>{date}</code>  {day_condition}  {temp_range}")

    forecast_block = "\n".join(forecast_lines) if forecast_lines else "—"

    text = (
        f"🌍 <b>{escape_html(city_name)}</b>\n\n"
        f"{condition}\n"
        f"🌡 <b>Температура:</b> {temp_str}\n"
        f"💧 <b>Влажность:</b> {humidity}%\n"
        f"💨 <b>Ветер:</b> {wind_ms} м/с, {wind_dir} ({wind_dir_deg}°)\n"
        f"👁 <b>Видимость:</b> {visibility} км\n"
        f"🔵 <b>Давление:</b> {pressure} мбар\n\n"
        f"📅 <b>Прогноз на 3 дня:</b>\n{forecast_block}"
    )
    return text

class WeatherModule(KitsuneModule):
    name        = "weather"
    description = "Weather by city"
    author      = "Yushi"
    version     = "1.0"
    icon        = "🌤"
    category    = "tools"

    strings_ru = {
        "no_city":   "❌ Укажи город: <code>.weather Москва</code>",
        "loading":   "⏳ Получаю погоду...",
        "error":     "❌ <b>Не удалось получить погоду</b>\n<code>{err}</code>",
        "not_found": "❌ Город <b>{city}</b> не найден.",
    }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.config = ModuleConfig(
            ConfigValue(
                "default_city",
                "",
                "Город по умолчанию (если не указан в команде)",
                validator=String(max_len=100),
            ),
            ConfigValue(
                "units",
                "C",
                "Единицы температуры: C (Цельсий) или F (Фаренгейт)",
                validator=Choice(["C", "F"]),
            ),
        )

    @command("weather", required=OWNER, aliases=["погода", "w"])
    async def weather_cmd(self, event) -> None:
        args = self.get_args(event)
        city = args.strip() if args else (self.config["default_city"] if self.config else "")

        if not city:
            await event.edit(self.strings("no_city"), parse_mode="html")
            return

        await event.edit(self.strings("loading"), parse_mode="html")

        try:
            data = await self._fetch_weather(city)
        except ValueError as exc:
            await event.edit(self.strings("not_found").format(city=escape_html(city)), parse_mode="html")
            return
        except Exception as exc:
            await event.edit(
                self.strings("error").format(err=escape_html(str(exc))), parse_mode="html"
            )
            return

        unit = self.config["units"] if self.config else "C"
        text = _parse_weather(data, unit)
        await event.edit(text, parse_mode="html", link_preview=False)

    async def _fetch_weather(self, city: str) -> dict:
        import aiohttp

        url = _WTTR_URL.format(city=city.replace(" ", "+"))

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=15),
                headers={"Accept-Language": "ru-RU,ru;q=0.9"},
            ) as resp:
                if resp.status == 404:
                    raise ValueError(f"City {city!r} not found")
                if resp.status != 200:
                    raise RuntimeError(f"HTTP {resp.status}")

                text = await resp.text()
                if not text.strip().startswith("{"):
                    raise ValueError(f"City {city!r} not found")

                import json
                return json.loads(text)
