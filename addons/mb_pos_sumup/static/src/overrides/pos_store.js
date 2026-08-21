import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";

patch(PosStore.prototype, {
    async handleUrlParams() {
        await super.handleUrlParams(...arguments);
        await this.mbSumupHandleCallback();
    },

    /**
     * Pick up a payment that was made while this page did not exist.
     *
     * The SumUp app returns the browser to the payment screen's own URL with
     * its result in the query string, so this boot is the continuation of the
     * payment the previous boot started.
     */
    async mbSumupHandleCallback() {
        const params = new URLSearchParams(window.location.search);
        if (!params.has("smp-status")) {
            return;
        }

        // Take the result out of the URL before acting on it. A cashier who
        // refreshes the page must not replay a payment, and a URL that stays in
        // the history is a URL that gets shared.
        const cleanUrl = new URL(window.location.href);
        cleanUrl.search = "";
        history.replaceState({}, "", cleanUrl);

        // `foreign-tx-id` is the payment line's own uuid, echoed back by the
        // supported SumUp app and required to identify the payment safely.
        const uuid = params.get("foreign-tx-id");
        const paymentLine = uuid && this.models["pos.payment"].find((line) => line.uuid === uuid);
        if (!paymentLine) {
            this.env.services.notification.add(
                _t("SumUp returned a payment that matches no open order."),
                { type: "warning" }
            );
            return;
        }

        const order = paymentLine.pos_order_id;
        if (order) {
            this.setOrder(order);
            this.navigate("PaymentScreen", { orderUuid: order.uuid });
        }

        await paymentLine.payment_method_id.payment_terminal?.finalizeFromCallback(
            paymentLine,
            Object.fromEntries(params)
        );
    },
});
