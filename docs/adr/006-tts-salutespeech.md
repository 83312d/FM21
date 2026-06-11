# ADR-006: TTS provider — SaluteSpeech

**Status:** Accepted (Path A assumptions, 2026-06-11)  
**Date:** 2026-06-11  
**Deciders:** Product owner  
**Requirements:** R20

## Context

News segments require Russian text-to-speech for 1–2 minute radio copy. Latency, voice quality, and container SSL compatibility matter for cron-driven materialization (U20).

## Decision

### 1. Provider: SaluteSpeech REST (sync)

- **Auth:** `POST https://ngw.devices.sberbank.ru:9443/api/v2/oauth` with `SALUTESPEECH_CREDENTIALS` (Base64 `client_id:secret`) and `SALUTESPEECH_SCOPE` (`SALUTE_SPEECH_PERS` closed beta).
- **Synthesis:** `POST https://smartspeech.sber.ru/rest/v1/text:synthesize?format=wav16&voice={SALUTESPEECH_VOICE}` (default `Nec_24000`).
- **Transport:** REST only — no gRPC / proto client in FM21.
- Token TTL ~30 min; client caches and refreshes.

### 2. Post-processing

- Transcode `wav16` → MP3 via ffmpeg before storage (ADR-008).
- ffprobe for `duration_sec` stored on news row / enqueue meta.

### 3. SSL in Docker

- Russian CA bundle may be required in containers.
- `SALUTESPEECH_VERIFY_SSL_CERTS` env (default `true`); mount CA bundle if verification fails in dev/CI.

### 4. TTS cache

- Redis key `fm21:tts:cache:{sha256(summary_ru)}` — repeat summary skips second API call (AE3).

## Consequences

- Closed beta tied to Sber SaluteSpeech ToS and personal/corp scope limits.
- Sync API ~4k char limit sufficient for 150–250 word summaries.
- Production voice / scope change requires env update only, not Liquidsoap changes.
