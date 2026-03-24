"""
Aircall Webhook Handler & Audio Transcription
Downloads Aircall recordings, transcribes via OpenAI, and hands off to the processor.
"""

import os
import io
import tempfile
import logging
import hashlib
import hmac
from datetime import datetime
from typing import Optional, Dict, Any

import requests
from openai import AzureOpenAI
from pydub import AudioSegment

logger = logging.getLogger(__name__)

# Configuration
AIRCALL_API_ID = os.environ.get("AIRCALL_API_ID", "")
AIRCALL_API_KEY = os.environ.get("AIRCALL_API_KEY", "")
AIRCALL_WEBHOOK_SECRET = os.environ.get("AIRCALL_WEBHOOK_SECRET", "")

# Azure OpenAI (serverless gpt-4o-mini-transcribe deployment)
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini-transcribe")

# 24MB threshold for chunking (OpenAI limit is 25MB, leave margin)
MAX_FILE_SIZE_BYTES = 24 * 1024 * 1024
# 1500s is the model's max duration — chunk if over 1400s to leave margin
MAX_DURATION_SECONDS = 1400
# 20-minute chunks in milliseconds
CHUNK_DURATION_MS = 20 * 60 * 1000


def fetch_call(call_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a call from the Aircall API and return parsed metadata (same format as webhook)."""
    resp = requests.get(
        f"https://api.aircall.io/v1/calls/{call_id}",
        auth=(AIRCALL_API_ID, AIRCALL_API_KEY),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json().get("call", {})

    recording_url = data.get("recording")
    if not recording_url:
        logger.info(f"No recording URL for call {call_id}")
        return None

    user = data.get("user") or {}
    contact = data.get("contact") or {}
    contact_name = ""
    if contact:
        first = contact.get("first_name", "")
        last = contact.get("last_name", "")
        contact_name = f"{first} {last}".strip()

    started_at = data.get("started_at")
    call_date = datetime.now().strftime("%Y-%m-%d")
    if started_at:
        try:
            call_date = datetime.fromtimestamp(started_at).strftime("%Y-%m-%d")
        except (ValueError, TypeError, OSError):
            pass

    return {
        "call_id": str(data.get("id", "")),
        "recording_url": recording_url,
        "aircall_user_id": str(user.get("id", "")),
        "user_name": user.get("name", ""),
        "caller_number": data.get("raw_digits", ""),
        "contact_name": contact_name,
        "call_date": call_date,
        "duration": data.get("duration", 0),
        "direction": data.get("direction", ""),
        "started_at": started_at,
        "ended_at": data.get("ended_at"),
    }


def verify_webhook_signature(payload_body: bytes, signature: str) -> bool:
    """Verify Aircall webhook signature if a secret is configured."""
    if not AIRCALL_WEBHOOK_SECRET:
        logger.warning("No AIRCALL_WEBHOOK_SECRET configured — skipping signature verification")
        return True

    expected = hmac.new(
        AIRCALL_WEBHOOK_SECRET.encode("utf-8"),
        payload_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


def _build_call_meta(data: dict, recording_pending: bool = False) -> Dict[str, Any]:
    """Build standardised call metadata dict from Aircall call data."""
    user = data.get("user") or {}
    contact = data.get("contact") or {}
    contact_name = ""
    if contact:
        first = contact.get("first_name", "")
        last = contact.get("last_name", "")
        contact_name = f"{first} {last}".strip()

    started_at = data.get("started_at")
    call_date = datetime.now().strftime("%Y-%m-%d")
    if started_at:
        try:
            call_date = datetime.fromtimestamp(started_at).strftime("%Y-%m-%d")
        except (ValueError, TypeError, OSError):
            pass

    return {
        "call_id": str(data.get("id", "")),
        "recording_url": data.get("recording") or "",
        "aircall_user_id": str(user.get("id", "")),
        "user_name": user.get("name", ""),
        "caller_number": data.get("raw_digits", ""),
        "contact_name": contact_name,
        "call_date": call_date,
        "duration": data.get("duration", 0),
        "direction": data.get("direction", ""),
        "started_at": started_at,
        "ended_at": data.get("ended_at"),
        "recording_pending": recording_pending,
    }


def poll_for_recording(call_id: str, max_attempts: int = 5, interval: int = 30) -> Optional[Dict[str, Any]]:
    """Poll the Aircall API until the recording URL is available."""
    import time
    for attempt in range(1, max_attempts + 1):
        time.sleep(interval)
        try:
            fetched = fetch_call(call_id)
            if fetched and fetched.get("recording_url"):
                logger.info(f"Recording URL found on attempt {attempt}/{max_attempts} for call {call_id}")
                return fetched
            logger.info(f"Poll attempt {attempt}/{max_attempts} for call {call_id} — still no recording")
        except Exception as e:
            logger.warning(f"Poll attempt {attempt}/{max_attempts} for call {call_id} failed: {e}")
    logger.info(f"No recording URL after {max_attempts} attempts for call {call_id} — giving up")
    return None


def parse_webhook_payload(payload: dict) -> Optional[Dict[str, Any]]:
    """
    Parse an Aircall call.ended webhook payload.
    Returns structured call metadata or None if the event should be ignored.
    If no recording URL yet, returns metadata with recording_pending=True.
    """
    event = payload.get("event")
    if event != "call.ended":
        logger.info(f"Ignoring Aircall event: {event}")
        return None

    data = payload.get("data", {})
    recording_url = data.get("recording")
    call_id = str(data.get("id", ""))

    if not recording_url:
        logger.info(f"No recording URL in call {call_id} — marking as pending")
        return _build_call_meta(data, recording_pending=True)

    return _build_call_meta(data)


def download_recording(recording_url: str) -> bytes:
    """Download the MP3 recording from Aircall.
    The recording URL from the webhook is a pre-signed S3 URL,
    so no auth headers should be sent (they conflict with the S3 signature).
    """
    logger.info(f"Downloading recording from Aircall...")

    response = requests.get(recording_url, timeout=300)
    response.raise_for_status()

    content = response.content
    size_mb = len(content) / (1024 * 1024)
    logger.info(f"Downloaded recording: {size_mb:.1f} MB")

    return content


def transcribe_audio(audio_content: bytes, duration_seconds: int = 0) -> str:
    """
    Transcribe audio using OpenAI gpt-4o-mini-transcribe.
    Chunks if file is over 24MB or duration exceeds 1400 seconds.
    """
    client = AzureOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_API_KEY,
        api_version="2025-03-01-preview",
    )

    needs_chunking = (
        len(audio_content) > MAX_FILE_SIZE_BYTES
        or duration_seconds > MAX_DURATION_SECONDS
    )

    if needs_chunking:
        reason = "size" if len(audio_content) > MAX_FILE_SIZE_BYTES else "duration"
        logger.info(f"Chunking audio ({reason}: {len(audio_content)/(1024*1024):.1f} MB, {duration_seconds}s)")
        return _transcribe_chunked(client, audio_content)
    else:
        return _transcribe_single(client, audio_content)


def _transcribe_single(client: AzureOpenAI, audio_content: bytes) -> str:
    """Transcribe a single audio file."""
    audio_file = io.BytesIO(audio_content)
    audio_file.name = "recording.mp3"

    response = client.audio.transcriptions.create(
        model=AZURE_OPENAI_DEPLOYMENT,
        file=audio_file,
        language="en",
    )

    return response.text


def _transcribe_chunked(client: AzureOpenAI, audio_content: bytes) -> str:
    """Split audio into 20-minute chunks, transcribe each, concatenate."""
    tmp_dir = tempfile.mkdtemp(prefix="aircall_")
    chunk_paths = []
    transcripts = []

    try:
        # Write full audio to temp file for pydub
        full_path = os.path.join(tmp_dir, "full_recording.mp3")
        with open(full_path, "wb") as f:
            f.write(audio_content)

        audio = AudioSegment.from_mp3(full_path)
        total_duration = len(audio)
        logger.info(f"Total audio duration: {total_duration / 1000 / 60:.1f} minutes")

        # Split into chunks
        chunk_index = 0
        start_ms = 0
        while start_ms < total_duration:
            end_ms = min(start_ms + CHUNK_DURATION_MS, total_duration)
            chunk = audio[start_ms:end_ms]

            chunk_path = os.path.join(tmp_dir, f"chunk_{chunk_index}.mp3")
            chunk.export(chunk_path, format="mp3")
            chunk_paths.append(chunk_path)

            logger.info(f"Chunk {chunk_index}: {start_ms/1000/60:.1f}m - {end_ms/1000/60:.1f}m")

            start_ms = end_ms
            chunk_index += 1

        # Transcribe each chunk
        for i, chunk_path in enumerate(chunk_paths):
            logger.info(f"Transcribing chunk {i+1}/{len(chunk_paths)}...")
            with open(chunk_path, "rb") as f:
                response = client.audio.transcriptions.create(
                    model=AZURE_OPENAI_DEPLOYMENT,
                    file=f,
                    language="en",
                )
                transcripts.append(response.text)

        return "\n\n".join(transcripts)

    finally:
        # Clean up temp files
        import shutil
        try:
            shutil.rmtree(tmp_dir)
            logger.info("Cleaned up temp files")
        except Exception as e:
            logger.warning(f"Failed to clean up temp dir {tmp_dir}: {e}")
