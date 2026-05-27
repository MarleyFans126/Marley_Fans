/** @odoo-module **/
/**
 * Floating AI Assistant panel.
 *
 * Mounted globally inside the backend webclient via a systray entry —
 * one collapsible drawer the salesperson can pop open from any view.
 * When the current view is a `crm.lead` form, quick-action buttons
 * become enabled and AI calls are anchored to that lead.
 */
import { Component, useState, useRef, onMounted, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { aiAssistant } from "@techmatic_ai_crm/services/ai_assistant_service";

const SAMPLE_PROMPTS = [
    "Summarize this lead",
    "Generate follow-up email",
    "What are my inactive opportunities?",
    "Suggest next action",
];

export class AIAssistantPanel extends Component {
    static template = "techmatic_ai_crm.AIAssistantPanel";
    static props = {};

    setup() {
        this.assistant = aiAssistant;
        this.notification = useService("notification");
        this.action = useService("action");
        this.scrollRef = useRef("scroll");

        this.state = useState({
            open: false,
            enabled: true,
            loading: false,
            sessionId: null,
            messages: [],
            input: "",
            samples: SAMPLE_PROMPTS,
        });

        onWillStart(async () => {
            try {
                const s = await this.assistant.status();
                this.state.enabled = !!s.enabled;
            } catch (e) {
                this.state.enabled = false;
            }
        });

        onMounted(() => {
            this._scrollBottom();
        });
    }

    /**
     * The active CRM lead id, if any. Read from the current action's
     * context — null on every non-lead view.
     */
    get currentLeadId() {
        const action = this.action.currentController;
        if (!action) return null;
        const props = action.props || {};
        if (props.resModel === "crm.lead" && props.resId) {
            return props.resId;
        }
        return null;
    }

    async togglePanel() {
        this.state.open = !this.state.open;
        if (this.state.open && !this.state.sessionId) {
            await this._loadSession();
        }
    }

    async _loadSession() {
        if (!this.state.enabled) return;
        this.state.loading = true;
        try {
            const res = await this.assistant.getOrCreateSession(this.currentLeadId);
            this.state.sessionId = res.session_id;
            this.state.messages = res.messages || [];
        } catch (e) {
            this.notification.add(e.message || _t("Failed to load AI session."), {
                type: "danger",
            });
        } finally {
            this.state.loading = false;
            this._scrollBottom();
        }
    }

    async newSession() {
        this.state.loading = true;
        try {
            const res = await this.assistant.newSession(this.currentLeadId);
            this.state.sessionId = res.session_id;
            this.state.messages = [];
        } catch (e) {
            this.notification.add(e.message, { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    useSample(prompt) {
        this.state.input = prompt;
    }

    async sendMessage() {
        const body = (this.state.input || "").trim();
        if (!body || this.state.loading) return;
        if (!this.state.sessionId) {
            await this._loadSession();
        }
        this.state.loading = true;
        // Optimistic append so the user sees their message right away.
        this.state.messages = [
            ...this.state.messages,
            { id: `tmp-${Date.now()}`, role: "user", body },
        ];
        this.state.input = "";
        this._scrollBottom();
        try {
            const res = await this.assistant.sendMessage(
                this.state.sessionId,
                body,
                this.currentLeadId,
            );
            this.state.messages = res.messages || this.state.messages;
        } catch (e) {
            this.notification.add(e.message || _t("AI request failed."), {
                type: "danger",
            });
        } finally {
            this.state.loading = false;
            this._scrollBottom();
        }
    }

    async quickAction(action) {
        const leadId = this.currentLeadId;
        if (!leadId) {
            this.notification.add(
                _t("Open a lead to use quick actions."),
                { type: "warning" },
            );
            return;
        }
        this.state.loading = true;
        try {
            const res = await this.assistant.leadQuickAction(leadId, action);
            this._appendAssistant(this._formatQuickActionResult(action, res.result));
            this.notification.add(_t("AI quick action completed."), { type: "success" });
        } catch (e) {
            this.notification.add(e.message || _t("Quick action failed."), {
                type: "danger",
            });
        } finally {
            this.state.loading = false;
        }
    }

    _formatQuickActionResult(action, result) {
        if (action === "summarize") {
            return `**Lead Summary**\n\n${result}`;
        }
        if (action === "score") {
            return [
                `**Lead Score**: ${result.score} / 100`,
                `**Status**: ${result.status}`,
                `**Priority**: ${result.priority}`,
                `**Reason**: ${result.reason}`,
            ].join("\n");
        }
        if (action === "suggest_activities") {
            if (!Array.isArray(result) || !result.length) {
                return _t("No suggestions returned.");
            }
            return [
                "**Suggested Actions**",
                ...result.map(
                    (s) =>
                        `- ${s.action || "task"} (in ${s.due_in_days ?? "?"}d): ${
                            s.summary || ""
                        }`,
                ),
            ].join("\n");
        }
        return JSON.stringify(result);
    }

    _appendAssistant(body) {
        this.state.messages = [
            ...this.state.messages,
            { id: `local-${Date.now()}`, role: "assistant", body },
        ];
        this._scrollBottom();
    }

    onInputKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.sendMessage();
        }
    }

    _scrollBottom() {
        // Defer to next tick — the new message may not be in the DOM yet.
        setTimeout(() => {
            const el = this.scrollRef.el;
            if (el) el.scrollTop = el.scrollHeight;
        }, 0);
    }
}

// Mount the panel into the systray so it's reachable from every view.
export const aiAssistantSystrayItem = {
    Component: AIAssistantPanel,
};
registry.category("systray").add("techmatic_ai_crm.AIAssistantPanel", aiAssistantSystrayItem, {
    sequence: 99,
});
