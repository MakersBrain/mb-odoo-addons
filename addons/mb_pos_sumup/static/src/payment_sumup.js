import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { PaymentInterface } from "@point_of_sale/app/utils/payment/payment_interface";
import { register_payment_method } from "@point_of_sale/app/services/pos_store";

/**
 * How long to wait for the SumUp app to take over the screen before deciding it
 * is not installed. Nothing else can tell us: opening an unhandled URL scheme
 * fails silently in both Safari and Chrome.
 */
const HANDOVER_TIMEOUT_MS = 20000;

export class PaymentSumUp extends PaymentInterface {
    setup() {
        super.setup(...arguments);
        // A reversal would need the SumUp app to expose one, and it does not.
        // Refunds go through the API instead, from a refund order.
        this.supports_reversals = false;
    }

    async sendPaymentRequest(uuid) {
        const paymentLine = this.pos.getOrder().getPaymentlineByUuid(uuid);
        if (paymentLine.amount < 0) {
            return this._refund(paymentLine);
        }
        return this._handOverToSumUp(paymentLine);
    }

    async sendPaymentCancel() {
        // The payment is happening inside the SumUp app; there is nothing here
        // to call off. Removing the line is the cashier saying they will not
        // record it, which is a local decision.
        return true;
    }

    /**
     * Leave the POS for the SumUp app.
     *
     * The returned promise resolves false only if the app never opened. When it
     * does open, this page is being unloaded and the promise is abandoned on
     * purpose: the result comes back through the callback, on the next boot.
     */
    async _handOverToSumUp(paymentLine) {
        const order = paymentLine.pos_order_id;
        let url;
        try {
            url = await this.pos.data.call("pos.payment.method", "sumup_prepare_payment", [
                this.payment_method_id.id,
                paymentLine.amount,
                paymentLine.uuid,
                window.location.origin + window.location.pathname,
                order?.getName?.() || "",
            ]);
        } catch (error) {
            this._showError(error);
            return false;
        }

        // The line has to exist on disk before the page is left, or the
        // callback comes back to an order that never had this payment on it.
        paymentLine.transaction_id = paymentLine.uuid;
        await this.pos.data.synchronizeLocalDataInIndexedDB();

        const handover = new Promise((resolve) => {
            setTimeout(() => {
                if (document.visibilityState === "visible") {
                    this._showError(
                        _t(
                            "The SumUp app did not open. Install it on this device, " +
                                "or record the payment another way."
                        )
                    );
                    resolve(false);
                }
            }, HANDOVER_TIMEOUT_MS);
        });
        window.location.href = url;
        return handover;
    }

    /**
     * Finish a payment line from the parameters SumUp put on the callback.
     *
     * Called on boot by the store override, not by the payment screen: by the
     * time this runs, the promise the screen was waiting on died with the
     * previous page.
     */
    async finalizeFromCallback(paymentLine, callbackParams) {
        let result;
        try {
            result = await this.pos.data.call("pos.payment.method", "sumup_confirm_payment", [
                this.payment_method_id.id,
                paymentLine.uuid,
                paymentLine.amount,
                callbackParams,
            ]);
        } catch (error) {
            this._showError(error);
            paymentLine.handlePaymentResponse(false);
            return false;
        }

        if (result.successful) {
            paymentLine.transaction_id = result.transaction_code || paymentLine.uuid;
            paymentLine.card_no = result.card_no || "";
            paymentLine.card_brand = result.card_brand || "";
            paymentLine.card_type = result.card_type || "";
            if (!result.verified) {
                // Say so on the ticket rather than in a dialog nobody keeps: an
                // unverified payment is one SumUp was never asked about.
                paymentLine.setReceiptInfo(_t("SumUp payment, unverified"));
            }
        } else {
            this._showError(result.message || _t("SumUp refused the payment."));
        }

        paymentLine.handlePaymentResponse(result.successful);
        await this.pos.data.synchronizeLocalDataInIndexedDB();
        return result.successful;
    }

    async _refund(refundLine) {
        const transactionCode = this._findOriginalTransactionCode(refundLine);
        if (!transactionCode) {
            this._showError(
                _t("Only an order that was paid with SumUp can be refunded to SumUp.")
            );
            return false;
        }

        let result;
        try {
            result = await this.pos.data.call("pos.payment.method", "sumup_refund_payment", [
                this.payment_method_id.id,
                transactionCode,
                Math.abs(refundLine.amount),
            ]);
        } catch (error) {
            this._showError(error);
            return false;
        }

        if (!result.successful) {
            this._showError(result.message || _t("SumUp refused the refund."));
            return false;
        }
        refundLine.transaction_id = transactionCode;
        return true;
    }

    _findOriginalTransactionCode(refundLine) {
        const currentOrder = refundLine.pos_order_id;
        const orderToRefund = currentOrder.lines[0]?.refunded_orderline_id?.order_id;
        if (!orderToRefund) {
            return null;
        }

        const amountDue = Math.abs(currentOrder.remainingDue);
        const originalLine = orderToRefund.payment_ids.find(
            (line) =>
                line.payment_method_id.use_payment_terminal === "sumup_mobile" &&
                line.amount <= amountDue
        );
        return originalLine?.transaction_id ?? null;
    }

    _extractErrorMessage(error) {
        if (typeof error === "string") {
            return error;
        }
        if (error.name === "RPC_ERROR") {
            return error.data.message;
        }
        return error.message;
    }

    _showError(error) {
        this.env.services.dialog.add(AlertDialog, {
            title: _t("SumUp Error"),
            body: this._extractErrorMessage(error),
        });
    }
}

register_payment_method("sumup_mobile", PaymentSumUp);
