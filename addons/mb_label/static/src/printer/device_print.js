/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { printerAdapter, printerAdapters } from "./printer_registry";
import { printerProfileId } from "../editor/printer_presets";
import { rememberAdapter, rememberedAdapter } from "./device_memory";
import "./system_adapter";
import "./phomemo_adapter";
import "./niimbot_adapter";

export class LabelDevicePrint extends Component {
    static template = "mb_label.LabelDevicePrint";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");
        this.state = useState({
            job: null, adapter: "system", busy: false, density: 10, speed: 5,
            bleAvailable: Boolean(globalThis.navigator?.bluetooth), printedCount: 0,
            adapters: printerAdapters().map((item) => ({
                id: item.id, label: item.label, available: item.available?.() !== false,
            })),
        });
        onWillStart(async () => {
            const jobId = this.props.action.context?.job_id;
            this.state.job = await this.orm.call("mb.label.print.job", "device_payload", [[jobId]]);
            const remembered = rememberedAdapter();
            const preferred = printerProfileId(this.state.job.printer_target);
            const destination = this.state.adapters.some(
                (item) => item.id === remembered && item.available) ? remembered : preferred;
            if (this.state.adapters.some((item) => item.id === destination && item.available)) {
                this.state.adapter = destination;
            }
        });
    }

    selectAdapter(event) {
        this.state.adapter = event.target.value;
        rememberAdapter(this.state.adapter);
    }

    async print() { return this._print(false); }

    async chooseAnother() { return this._print(true); }

    async _print(forceChooser) {
        const adapter = printerAdapter(this.state.adapter);
        if (!adapter || !this.state.job || this.state.busy) return;
        rememberAdapter(this.state.adapter);
        this.state.busy = true;
        try {
            await adapter.print(this.state.job, {
                density: this.state.adapter === "niimbot" ? Math.min(5, this.state.density) : this.state.density,
                speed: this.state.speed,
                forceChooser,
            });
            await this.orm.call("mb.label.print.job", "mark_printed", [[this.state.job.id], this.state.adapter]);
            this.state.printedCount++;
            this.notification.add("The label was sent. This window remains open for repeat printing.", { type: "success" });
        } catch (error) {
            const cancelled = error?.name === "NotFoundError";
            if (!cancelled) this.notification.add(error.message || "Printing failed.", { type: "danger", sticky: true });
        } finally {
            this.state.busy = false;
        }
    }

    downloadPdf() { window.open(`${this.state.job.pdf_url}?download=1`, "_self"); }
    close() { this.action.doAction({ type: "ir.actions.act_window_close" }); }
}

registry.category("actions").add("mb_label.device_print", LabelDevicePrint);
