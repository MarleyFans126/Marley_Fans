from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ── Core settings ──
    indiamart_active = fields.Boolean(
        string="Active IndiaMART Integration",
        related='indiamart_config_id.is_active', readonly=False,
    )
    indiamart_api_key = fields.Char(
        string="IndiaMART API Key (glusr_crm_key)",
        related='indiamart_config_id.api_key', readonly=False,
    )
    indiamart_api_base_url = fields.Char(
        string="IndiaMART API URL",
        related='indiamart_config_id.api_base_url', readonly=False,
    )
    indiamart_is_mock_server = fields.Boolean(
        string="Use Mock Server",
        related='indiamart_config_id.is_mock_server', readonly=False,
    )

    # ── Key generation & historical backfill ──
    indiamart_key_generated_date = fields.Datetime(
        string="Key Generated Date",
        related='indiamart_config_id.key_generated_date', readonly=False,
    )
    indiamart_historical_sync_done = fields.Boolean(
        string="Historical Sync Done",
        related='indiamart_config_id.historical_sync_done', readonly=True,
    )
    indiamart_historical_sync_cursor = fields.Datetime(
        string="Historical Sync Cursor",
        related='indiamart_config_id.historical_sync_cursor', readonly=True,
    )

    # ── Status (read-only) ──
    indiamart_last_sync_datetime = fields.Datetime(
        string="Last Sync Date",
        related='indiamart_config_id.last_sync_datetime', readonly=True,
    )
    indiamart_last_start_time = fields.Datetime(
        string="Last API Start Time",
        related='indiamart_config_id.last_start_time', readonly=True,
    )
    indiamart_last_end_time = fields.Datetime(
        string="Last API End Time",
        related='indiamart_config_id.last_end_time', readonly=True,
    )

    # ── Singleton config link ──
    indiamart_config_id = fields.Many2one(
        'indiamart.config', string="IndiaMART Config",
        compute='_compute_indiamart_config_id',
    )

    def _compute_indiamart_config_id(self):
        config = self.env['indiamart.config'].search([], limit=1)
        if not config:
            config = self.env['indiamart.config'].create({})
        for record in self:
            record.indiamart_config_id = config
