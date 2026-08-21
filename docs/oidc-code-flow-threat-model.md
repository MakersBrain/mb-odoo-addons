# OIDC authorization-code adapter threat model

The browser receives only a Rauthy authorization code. Odoo stores the login
attempt identifier, random state, PKCE verifier, nonce, creation time, provider,
and a local return target in its server-side session. The attempt is atomically
removed before exchanging the code and expires after five minutes.

- **Callback CSRF and login substitution:** a fresh high-entropy state value is
  compared to the session attempt. Missing, expired, or mismatched state fails
  before token exchange.
- **Code interception:** PKCE S256 binds the single-use Rauthy code to the
  verifier held in the Odoo session. Token redemption uses a bounded HTTPS
  request with normal certificate validation.
- **Token substitution and key rotation:** Odoo does not parse or trust token
  claims. It sends both tokens and the expected nonce to the workshop-scoped
  control API, whose existing discovery/JWKS cache validates RS256, exact
  issuer, the deterministic tenant audience, expiry, nonce, and `at_hash` when
  present. JWKS refresh remains centralized there.
- **Replay:** the Odoo attempt is consumed before any network request. A lost
  response therefore requires a fresh login; tokens, nonce, verifier, and
  claims are never stored in an Odoo model.
- **Cross-tenant confusion:** the workshop is selected by the internal API path
  and authenticated tenant credential, never by a request-body claim. Odoo
  accepts only the allowlisted stable subject and links only an already
  provisioned user for the configured provider.
- **Control-API outage:** timeout, TLS, malformed response, or non-success status
  fails closed. Upstream response bodies and bearer material are not logged or
  copied into redirects and errors.
