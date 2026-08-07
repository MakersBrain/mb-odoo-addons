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
            model: "auto", align: "auto", feed: 32,
            continuous: false, dither: "threshold", diagnostic: "",
            phomemoModels: [],
            ditherModes: [
                ["threshold", "Threshold (sharp)"],
                ["floyd-steinberg", "Floyd-Steinberg (photo)"],
                ["atkinson", "Atkinson (light)"],
                ["ordered", "Ordered pattern"],
            ],
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
            const phomemo = printerAdapter("phomemo");
            const settings = phomemo?.settings?.() || {};
            Object.assign(this.state, {
                model: settings.model || "auto",
                align: settings.align || "auto",
                feed: settings.feed ?? 32,
                continuous: Boolean(settings.continuous),
                dither: settings.dither || "threshold",
                density: settings.density ?? 10,
                speed: settings.speed ?? 5,
                phomemoModels: phomemo?.models?.() || [],
            });
        });
    }

    selectAdapter(event) {
        this.state.adapter = event.target.value;
        this.state.diagnostic = "";
        rememberAdapter(this.state.adapter);
    }

    phomemoOptions(forceChooser = false) {
        return {
            model: this.state.model,
            align: this.state.align === "auto" ? undefined : this.state.align,
            feed: Number(this.state.feed),
            continuous: Boolean(this.state.continuous),
            dither: this.state.dither,
            density: Number(this.state.density),
            speed: Number(this.state.speed),
            forceChooser,
        };
    }

    updatePhomemoSetting(event) {
        const key = event.currentTarget.dataset.setting;
        const value = event.currentTarget.type === "checkbox"
            ? event.currentTarget.checked : event.currentTarget.value;
        this.state[key] = value;
        printerAdapter("phomemo")?.saveSettings?.(this.phomemoOptions());
    }

    updateDensity(event) {
        this.state.density = event.currentTarget.value;
        if (this.state.adapter === "phomemo") {
            printerAdapter("phomemo")?.saveSettings?.(this.phomemoOptions());
        }
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
                ...(this.state.adapter === "phomemo"
                    ? this.phomemoOptions(forceChooser)
                    : {
                        density: Math.min(5, Number(this.state.density)),
                        speed: Number(this.state.speed),
                        forceChooser,
                    }),
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

    async testConnection() {
        const adapter = printerAdapter("phomemo");
        if (!adapter?.testConnection || this.state.busy) return;
        this.state.busy = true;
        this.state.diagnostic = "";
        try {
            this.state.diagnostic = await adapter.testConnection(this.phomemoOptions());
            this.notification.add("Printer connection is healthy.", { type: "success" });
        } catch (error) {
            this.state.diagnostic = error.message || "Connection test failed.";
            this.notification.add(this.state.diagnostic, { type: "danger", sticky: true });
        } finally {
            this.state.busy = false;
        }
    }

    async testPhomemoPrint() {
        const adapter = printerAdapter("phomemo");
        if (!adapter?.testPrint || this.state.busy) return;
        this.state.busy = true;
        try {
            const result = await adapter.testPrint(this.phomemoOptions());
            this.notification.add(
                `Test pattern sent (${result.bytes} bytes, ${(result.ink * 100).toFixed(1)}% ink).`,
                { type: "success" }
            );
        } catch (error) {
            this.notification.add(error.message || "Test print failed.", {
                type: "danger", sticky: true,
            });
        } finally {
            this.state.busy = false;
        }
    }

    downloadPdf() { window.open(`${this.state.job.pdf_url}?download=1`, "_self"); }
    close() { this.action.doAction({ type: "ir.actions.act_window_close" }); }
}

registry.category("actions").add("mb_label.device_print", LabelDevicePrint);
