/** @odoo-module **/

import { registerPrinterAdapter } from "./printer_registry";

registerPrinterAdapter({
    id: "system",
    label: "System print dialog / Save as PDF",
    available: () => typeof window?.print === "function",
    async print(job) {
        window.open(`${job.print_url}?autoprint=1`, "_blank", "noopener");
    },
});
