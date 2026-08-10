import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { patch } from "@web/core/utils/patch";

patch(PaymentScreen.prototype, {
    async addNewPaymentLine(paymentMethod) {
        if (paymentMethod.use_payment_terminal === "sumup_mobile" && this.isRefundOrder) {
            const refundedOrder = this.currentOrder.lines[0]?.refunded_orderline_id?.order_id;
            const amountDue = Math.abs(this.currentOrder.remainingDue);
            const matchedPaymentLine = refundedOrder?.payment_ids.find(
                (line) =>
                    line.payment_method_id.use_payment_terminal === "sumup_mobile" &&
                    line.amount >= amountDue &&
                    line.transaction_id
            );
            if (matchedPaymentLine) {
                const added = await super.addNewPaymentLine(paymentMethod);
                if (added) {
                    this.paymentLines.at(-1).updateRefundPaymentLine(matchedPaymentLine);
                }
                return added;
            }
        }
        return await super.addNewPaymentLine(paymentMethod);
    },
});
