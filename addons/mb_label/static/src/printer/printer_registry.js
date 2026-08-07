/** @odoo-module **/

const adapters = new Map();

export function registerPrinterAdapter(adapter) {
    if (!adapter?.id || typeof adapter.print !== "function") {
        throw new Error("Invalid label printer adapter.");
    }
    adapters.set(adapter.id, adapter);
}

export function printerAdapters() {
    return [...adapters.values()];
}

export function printerAdapter(id) {
    return adapters.get(id);
}
