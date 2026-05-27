# -*- coding: utf-8 -*-
"""Shared test scaffolding.

* ``FakeProvider`` — stub for the AI provider so tests never hit the
  real OpenAI / Gemini APIs.
* ``AICRMTestCase`` — patches ``AIService.provider`` to return the
  fake, seeds a minimal ``crm.lead``, and exposes helper users.
"""
from contextlib import contextmanager
from unittest.mock import patch

from odoo.tests.common import TransactionCase

from ..services.ai_provider import AIProvider
from ..services import ai_service as ai_service_mod


class FakeProvider(AIProvider):
    """Returns canned strings. Tests inject ``responses`` per call type."""
    name = 'fake'

    def __init__(self, config=None):
        # Bypass parent validation — tests don't need a real API key.
        self.api_key = 'TEST'
        self.model = 'fake-model'
        self.temperature = 0.0
        self.max_tokens = 100
        self.timeout = 5
        self.responses = []          # FIFO queue
        self.calls = []              # captured (messages, kwargs)

    def queue(self, *texts):
        self.responses.extend(texts)
        return self

    def _chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if self.responses:
            return self.responses.pop(0)
        return 'OK'


@contextmanager
def patched_provider(fake):
    """Force ``AIService`` to hand out ``fake`` for the block's duration."""
    with patch.object(
            ai_service_mod.AIService, 'provider', lambda self: fake,
    ):
        yield fake


class AICRMTestCase(TransactionCase):
    """Common base. Mocks the provider and seeds a CRM lead + AI users."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ICP = cls.env['ir.config_parameter'].sudo()
        # Seed minimal config so AIService.is_enabled() is True without
        # contacting an external API.
        cls.ICP.set_param('techmatic_ai_crm.enabled', 'True')
        cls.ICP.set_param('techmatic_ai_crm.provider', 'openai')
        cls.ICP.set_param('techmatic_ai_crm.api_key', 'sk-test')
        cls.ICP.set_param('techmatic_ai_crm.model', 'fake-model')
        cls.ICP.set_param('techmatic_ai_crm.rate_limit', '1000')

        cls.group_user = cls.env.ref(
            'techmatic_ai_crm.group_techmatic_ai_crm_user')
        cls.group_admin = cls.env.ref(
            'techmatic_ai_crm.group_techmatic_ai_crm_admin')

        Users = cls.env['res.users'].with_context(no_reset_password=True)
        cls.user_sales = Users.create({
            'name': 'AI Sales User',
            'login': 'ai_sales_user',
            'email': 'ai_sales_user@example.com',
            'group_ids': [(4, cls.group_user.id)],
        })
        # Admin needs ``base.group_system`` to create res.config.settings;
        # that's the standard Odoo prerequisite for any settings screen.
        cls.user_admin = Users.create({
            'name': 'AI Admin',
            'login': 'ai_admin',
            'email': 'ai_admin@example.com',
            'group_ids': [
                (4, cls.group_admin.id),
                (4, cls.env.ref('base.group_system').id),
            ],
        })
        cls.user_outsider = Users.create({
            'name': 'Outsider',
            'login': 'ai_outsider',
            'email': 'ai_outsider@example.com',
            'group_ids': [(4, cls.env.ref('base.group_user').id)],
        })

        cls.lead = cls.env['crm.lead'].with_user(cls.user_sales).create({
            'name': 'Test AI Lead',
            'type': 'opportunity',
            'email_from': 'lead@example.com',
            'phone': '+1 555 0100',
            'description': 'Customer interested in 200 units urgent.',
            'expected_revenue': 75000.0,
            'probability': 35.0,
            # Lock the shared seed lead so it never gets picked up by
            # background crons. Tests that want it processed can reset
            # these flags. Without this the orchestrator + auto-process
            # crons would consume fake-provider responses meant for
            # the per-test scratch leads.
            'ai_auto_processed': True,
            'ai_outreach_initialized': True,
            'ai_legitimacy_verdict': 'verified',
            'ai_legitimacy_score': 70,
            'ai_handed_off': True,  # never reply to / outreach this seed
        })

    def _new_fake(self, *responses):
        fake = FakeProvider()
        if responses:
            fake.queue(*responses)
        return fake
