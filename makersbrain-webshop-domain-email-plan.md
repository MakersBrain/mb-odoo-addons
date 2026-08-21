# Webshop, Domain, and Email: Remaining Qualification Plan

Status: paid-release implementation complete locally; external qualification open

Implemented architecture and behavior are described by `SPEC.md`, addon READMEs,
and the control-plane release contract. The first paid release still requires a
signed artifact for one immutable staging build covering:

1. two-tenant hostname, database-filter, cookie, cache, attachment, websocket,
   worker, and background-job isolation over real DNS and TLS;
2. live Cloudflare custom-hostname ownership, certificate issuance, redirect,
   disconnect, rotation, outage, and reconciliation behavior;
3. live Scaleway transactional-mail registration, SPF/DKIM/DMARC observation,
   delivery, deferred delivery, bounce, complaint, suppression, fallback,
   revocation, and recovery drills;
4. hosted payment success, failure, refund, delayed/replayed callback, invoice,
   stock, and reconciliation behavior for the exact staged release;
5. merchant-approved carrier label, tracking, return, cancellation, and delivery
   exception journeys;
6. representative desktop/mobile storefront content, editor, checkout, pickup,
   accessibility, localization, email, portal return, and recovery journeys; and
7. production-like multiworker load, retry, queue backlog, provider outage,
   secret rotation, backup/restore, and deactivation/reactivation drills.

Partial-credit-note merchant UX and any future domain-sale, mailbox-hosting, or
overlay-removal capability remain separate product decisions. They are not
implicit requirements of the current release and must not weaken preservation of
ERP history, domain state, mail state, payments, returns, or customer evidence.
