/** @odoo-module **/
/**
 * Hide the chatter message Edit / Delete actions from non-admin users.
 *
 * Log notes & messages stay fully VISIBLE to everyone (read is never
 * restricted) — but only administrators may edit or delete them.
 *
 * Both the "Edit" and "Delete" message actions gate on `message.editable`
 * (see mail/static/src/core/common/message_actions.js), so making that
 * getter admin-only removes both pencil/trash icons for regular users and
 * also disables inline edit mode.
 *
 * This is the UI half of the rule; the hard enforcement lives in the
 * backend `mail.message` guard (mail_message_access.py) which blocks the
 * write/unlink even if the action is reached another way.
 */
import { patch } from "@web/core/utils/patch";
import { user } from "@web/core/user";
import { Message } from "@mail/core/common/message_model";

patch(Message.prototype, {
    get editable() {
        if (!user.isAdmin) {
            return false;
        }
        return super.editable;
    },
});
