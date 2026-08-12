/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registerPrinterAdapter } from "./printer_registry";

registerPrinterAdapter({
    id: "system",
    label: _t("System print dialog / Save as PDF"),
    available: () => typeof window?.print === "function",
    async print(job) {
        window.open(`${job.print_url}?autoprint=1`, "_blank", "noopener");
    },
});
