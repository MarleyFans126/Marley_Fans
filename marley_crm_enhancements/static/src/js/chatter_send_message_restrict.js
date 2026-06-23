/** @odoo-module **/
/**
 * Restrict the chatter "Send message" button to administrators only.
 * Non-admin users will not see / cannot use the "Send message" button
 * (the "Log note" button is left untouched). This is a UI restriction.
 */
import { patch } from "@web/core/utils/patch";
import { user } from "@web/core/user";
import { Chatter } from "@mail/chatter/web_portal/chatter";

patch(Chatter.prototype, {
    /** True only for administrators — gates the Send message button. */
    get marleyCanSendMessage() {
        return user.isAdmin;
    },
});
