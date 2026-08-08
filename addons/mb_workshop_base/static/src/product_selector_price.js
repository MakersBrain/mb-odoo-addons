/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { Many2One } from "@web/views/fields/many2one/many2one";

const PRODUCT_MODELS = new Set(["product.product", "product.template"]);

patch(Many2One.prototype, {
    get many2XAutocompleteProps() {
        const props = super.many2XAutocompleteProps;
        if (!PRODUCT_MODELS.has(this.props.relation)) {
            return props;
        }
        return {
            ...props,
            context: {
                ...props.context,
                mb_show_product_selector_price: true,
            },
        };
    },
});
