/** @odoo-module **/
/**
 * Front-end transport for the AI CRM Assistant.
 *
 * In Odoo 19, ``rpc`` is a top-level function (not a service), so this
 * module exports a plain object instead of registering with the
 * services registry. Components import ``aiAssistant`` directly.
 *
 * Public API:
 *   - status()                                     → { enabled }
 *   - getOrCreateSession(leadId?)                  → { session_id, title, messages }
 *   - newSession(leadId?)                          → { session_id, title, messages }
 *   - sendMessage(sessionId, body, leadId?)        → { messages }
 *   - leadQuickAction(leadId, action)              → { result }
 */
import { rpc } from "@web/core/network/rpc";

async function call(route, payload = {}) {
    const res = await rpc(route, payload);
    if (!res || !res.ok) {
        throw new Error((res && res.error) || "AI assistant error.");
    }
    return res;
}

export const aiAssistant = {
    status() {
        return call("/techmatic_ai_crm/status");
    },
    getOrCreateSession(leadId = null) {
        return call("/techmatic_ai_crm/session/get_or_create", { lead_id: leadId });
    },
    newSession(leadId = null) {
        return call("/techmatic_ai_crm/session/new", { lead_id: leadId });
    },
    sendMessage(sessionId, body, leadId = null) {
        return call("/techmatic_ai_crm/session/send", {
            session_id: sessionId,
            body,
            lead_id: leadId,
        });
    },
    leadQuickAction(leadId, action) {
        return call("/techmatic_ai_crm/lead/quick_action", {
            lead_id: leadId,
            action,
        });
    },
};
