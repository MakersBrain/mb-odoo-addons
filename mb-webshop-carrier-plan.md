# Webshop Carrier: Remaining Work

Status: current runtime and Boxtal/Sendcloud providers implemented; open work only

Current behavior belongs in `SPEC.md` and the carrier addon documentation. The
remaining roadmap is:

1. Qualify charged outbound labels for both providers and Sendcloud return
   labels with merchant-approved production accounts, including cancellation,
   webhook loss, delayed documents, tracking, refunds, and provider-support
   escalation.
2. Decide whether Boxtal return labels are commercially and technically
   available for the merchant account. Implement them only against a documented
   current API; otherwise keep Boxtal outbound-only.
3. Add multi-parcel shipments only after defining per-parcel stock/picking
   ownership, pricing, labels, cancellation, tracking, returns, and partial
   failure recovery. The current release remains one parcel per shipment.
4. Consider direct Mondial Relay, Colissimo, or Chronopost addons only after a
   merchant has the corresponding contract and current API credentials. Each
   addon must implement the existing provider contract without changing the
   provider-neutral runtime.
5. Capture exact-release staging evidence for pickup checkout, label purchase,
   signed callbacks, tracking mail, exception handling, retention, concurrency,
   and tenant isolation before production promotion.

Every mutation test must prove whether replay and reconciliation are safe for
that exact operation. An ambiguous provider outcome must remain explicit.
