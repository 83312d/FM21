# ADR-009: LLM summarization — GigaChat

**Status:** Accepted (Path A assumptions, 2026-06-11)  
**Date:** 2026-06-11  
**Deciders:** Product owner  
**Requirements:** R19, R22

## Context

RSS articles need Russian radio copy (150–250 words) before TTS. Word count, tone, and API transport must be consistent for closed beta.

## Decision

### 1. Provider: GigaChat via official Python SDK

- Credentials: `GIGACHAT_CREDENTIALS`; optional `GIGACHAT_SCOPE=GIGACHAT_API_PERS`.
- **REST only** through SDK — no alternate gRPC transport in FM21.

### 2. Prompt policy

- IT news tone; continuous prose for radio — **no bullet lists**.
- Target **150–250 Russian words**.
- Validator rejects out-of-range; **one retry** with tightened prompt, then `status=failed`.

### 3. Idempotency

- Rows already `summarized` or beyond are skipped on re-run.
- Summary text hashed for downstream TTS cache (ADR-006).

### 4. CI vs manual

- CI uses mocked GigaChat client.
- Spot-check 3 live Russian summaries with real credentials outside CI (orchestrator manual step).

## Consequences

- Closed beta tied to Sber GigaChat ToS and personal API scope.
- English source articles summarized to Russian — aligned with Habr/3DNews mixed-language feeds.
