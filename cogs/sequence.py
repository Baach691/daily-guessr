"""Mode "Remets dans l'ordre" : cinq messages consécutifs à réordonner."""

import logging
import random
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import discord

import config
import database
import filters
from cogs.daily import _pickable_channels, _user_avatar_url, global_name

log = logging.getLogger(__name__)

MODE = database.MODE_SEQUENCE
MESSAGE_COUNT = 5
MAX_GAP = timedelta(minutes=30)


def _truncate(text: str, limit: int = 500) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _payload(message: discord.Message) -> Dict:
    media_url = filters.media_attachment_url(message)
    media_name = ""
    if media_url:
        attachments = getattr(message, "attachments", []) or []
        media_name = getattr(attachments[0], "filename", "") if attachments else ""
    media_probe = media_name or media_url or ""
    return {
        "id": str(message.id),
        "author_id": str(message.author.id),
        "author_name": global_name(message.author),
        "content": _truncate(message.content),
        "has_media": bool(media_url),
        "media_url": media_url or "",
        "media_is_video": media_probe.lower().split("?")[0].endswith(
            (".mp4", ".mov", ".webm", ".mkv", ".m4v")
        ),
    }


async def _pick_sequence_daily_live(
    guild_id: int,
    channels: List[discord.TextChannel],
) -> Optional[Tuple[discord.TextChannel, List[discord.Message]]]:
    """Cherche une fenêtre chronologique de cinq messages humains éligibles."""
    if not channels:
        return None
    try:
        oldest = date.fromisoformat(config.OLDEST_MESSAGE_DATE)
    except Exception:
        oldest = date(2023, 10, 1)
    today = date.today()
    span_days = max(0, (today - oldest).days)
    blacklist = set(getattr(config, "BLACKLIST_USER_IDS", []) or [])
    recent_ids = database.get_recent_picks_set(
        guild_id,
        limit=config.RECENT_PICKS_EXCLUDE,
        mode=MODE,
    )

    for attempt_idx in range(5):
        channel = random.choice(channels)
        target = oldest + timedelta(days=random.randint(0, span_days))
        for window in (7, 30, 90):
            low_d = max(oldest, target - timedelta(days=window))
            high_d = min(today + timedelta(days=1), target + timedelta(days=window + 1))
            after_dt = datetime.combine(low_d, datetime.min.time(), tzinfo=timezone.utc)
            before_dt = datetime.combine(high_d, datetime.min.time(), tzinfo=timezone.utc)

            eligible: List[discord.Message] = []
            try:
                async for message in channel.history(
                    after=after_dt,
                    before=before_dt,
                    limit=300,
                    oldest_first=True,
                ):
                    if message.author.id in blacklist:
                        continue
                    if database.is_opted_out(message.author.id, guild_id):
                        continue
                    if not filters.is_sequence_eligible(
                        message,
                        config.MIN_CHARS,
                        config.MIN_WORDS,
                    ):
                        continue
                    eligible.append(message)
            except discord.DiscordException as error:
                log.warning(
                    "Séquence: erreur fetch (#%s, %s): %s",
                    channel.name,
                    target,
                    error,
                )
                continue

            candidates = []
            for index in range(len(eligible) - MESSAGE_COUNT + 1):
                group = eligible[index:index + MESSAGE_COUNT]
                if any(message.id in recent_ids for message in group):
                    continue
                if any(
                    later.created_at - earlier.created_at > MAX_GAP
                    for earlier, later in zip(group, group[1:])
                ):
                    continue
                candidates.append(group)

            log.info(
                "Séquence pick #%d ±%dj dans #%s : éligibles=%d, fenêtres=%d",
                attempt_idx + 1,
                window,
                channel.name,
                len(eligible),
                len(candidates),
            )
            if candidates:
                return channel, random.choice(candidates)
    return None


async def ensure_sequence_daily_for_guild(
    guild: discord.Guild,
    date_str: str,
    *,
    label: str = "daily",
) -> Tuple[bool, Optional[str]]:
    """Crée le défi séquence du jour s'il manque."""
    if database.get_sequence_daily(guild.id, date_str) is not None:
        return True, None
    channels = _pickable_channels(guild)
    if not channels:
        return False, "Aucun salon accessible pour préparer la conversation."

    try:
        picked = await _pick_sequence_daily_live(guild.id, channels)
    except Exception:
        log.exception("Séquence (%s) : exception pour %s.", label, guild.name)
        return False, "Une erreur est survenue pendant le tirage de la conversation."
    if picked is None:
        return False, "Pas assez de messages consécutifs éligibles pour ce mode."

    channel, messages = picked
    payloads = []
    for message in messages:
        database.upsert_user(
            guild.id,
            message.author.id,
            global_name(message.author),
            _user_avatar_url(message.author),
        )
        payloads.append(_payload(message))

    created = database.create_sequence_daily_if_absent(
        guild.id,
        date_str,
        channel.id,
        payloads,
    )
    if created:
        for message in messages:
            database.record_pick(guild.id, message.id, mode=MODE)
        log.info(
            "Séquence (%s) ✅ pour %s : messages #%s à #%s dans #%s.",
            label,
            guild.name,
            messages[0].id,
            messages[-1].id,
            channel.name,
        )
    return database.get_sequence_daily(guild.id, date_str) is not None, None
