# MakersBrain AI bridge

Shared Odoo boundary for addons that need OCR, multimodal extraction, or another
AI capability. It deliberately does not implement provider clients and stores no
provider credentials.

Domain addons extend the abstract `mb.ai.gateway` model with a fixed task name
and control-plane path. They submit JSON descriptors and content digests through
`submit()`; arbitrary URLs, embedded image bytes, credentials, oversized payloads,
unsafe operation keys, redirects, and malformed acceptance responses are rejected.
Latency-bounded normalized capabilities such as a shared-cache product lookup use
`request()` and must be explicitly registered with `mode = "request"`; callers
still cannot choose a URL or provider.

Callbacks remain domain-specific because inventory and accounting have different
authorization and review rules. They reuse `validate_callback_envelope()` to
enforce provider/model/attempt metadata and the no-raw-provider-body policy.

The Rust extraction broker owns Azure, Gemini, OpenAI, and Claude adapters,
provider secrets, model allowlists, schema conversion, retry/rate-limit behavior,
quota accounting, and primary/secondary routing. Business addons own prompts,
task schemas, normalized domain candidates, evidence, and every final write.
