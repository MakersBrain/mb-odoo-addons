/** @odoo-module **/

let enabled = false;

/** Enable bounded printer diagnostics only for an explicit support session. */
export function setPrinterProtocolDebug(value) {
    enabled = Boolean(value);
}

/**
 * Log a redacted protocol event.
 *
 * Vendored callers historically supplied device names, exception text and raw
 * byte arrays. Those arguments are deliberately discarded. Only a controlled
 * event token and scalar counters/flags from a plain summary object can leave
 * this boundary.
 */
export function printerProtocolDebug(event, summary = {}) {
    if (!enabled) {
        return;
    }
    const safeEvent =
        typeof event === "string" && /^[a-z][a-z0-9_.-]*$/i.test(event)
            ? event
            : "protocol-event";
    const safeSummary = {};
    if (summary && Object.getPrototypeOf(summary) === Object.prototype) {
        for (const [key, value] of Object.entries(summary)) {
            if (
                /^[a-z][a-z0-9_]*$/i.test(key) &&
                (typeof value === "number" || typeof value === "boolean")
            ) {
                safeSummary[key] = value;
            }
        }
    }
    console.debug(`[Phomymo] ${safeEvent}`, safeSummary);
}
