import logging

import httpx

from agent.state import AuraState
from config import settings

logger = logging.getLogger(__name__)


async def voice_transcriber(state: AuraState) -> dict:
    """Download voice note from WhatsApp and transcribe via Deepgram.

    Steps:
    1. Fetch the media URL from WhatsApp using media_id.
    2. Download the audio bytes.
    3. Send to Deepgram for transcription.
    4. Return the transcript text.
    """
    media_id = state.get("media_id")
    if not media_id:
        return {"transcription": ""}

    headers = {"Authorization": f"Bearer {settings.whatsapp_token}"}

    try:
        async with httpx.AsyncClient() as client:
            # Step 1: Get media URL from WhatsApp
            meta_resp = await client.get(
                f"https://graph.facebook.com/v18.0/{media_id}",
                headers=headers,
            )
            meta_resp.raise_for_status()
            media_url = meta_resp.json()["url"]

            # Step 2: Download audio
            audio_resp = await client.get(media_url, headers=headers)
            audio_resp.raise_for_status()
            audio_bytes = audio_resp.content

            # Step 3: Transcribe via Deepgram
            dg_resp = await client.post(
                "https://api.deepgram.com/v1/listen?model=nova-2&smart_format=true",
                headers={
                    "Authorization": f"Token {settings.deepgram_api_key}",
                    "Content-Type": "audio/ogg",
                },
                content=audio_bytes,
            )
            dg_resp.raise_for_status()
            transcript = (
                dg_resp.json()
                .get("results", {})
                .get("channels", [{}])[0]
                .get("alternatives", [{}])[0]
                .get("transcript", "")
            )
    except Exception:
        logger.exception("Voice transcription failed for media_id=%s", media_id)
        return {"transcription": ""}

    logger.info("Transcribed voice note: %s chars", len(transcript))
    return {"transcription": transcript}
