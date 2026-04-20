from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ── Core settings (plain fields, synced via get/set_values) ──
    indiamart_active = fields.Boolean(
        string="Active IndiaMART Integration",
    )
    indiamart_api_key = fields.Char(
        string="IndiaMART API Key (glusr_crm_key)",
    )
    indiamart_api_base_url = fields.Char(
        string="IndiaMART API URL",
    )
    indiamart_is_mock_server = fields.Boolean(
        string="Use Mock Server",
    )

    # ── Key generation & historical backfill ──
    indiamart_key_generated_date = fields.Datetime(
        string="Key Generated Date",
    )
    indiamart_historical_sync_done = fields.Boolean(
        string="Historical Sync Done",
        readonly=True,
    )
    indiamart_historical_sync_cursor = fields.Datetime(
        string="Historical Sync Cursor",
        readonly=True,
    )

    # ── Status (read-only) ──
    indiamart_last_sync_datetime = fields.Datetime(
        string="Last Sync Date",
        readonly=True,
    )
    indiamart_last_start_time = fields.Datetime(
        string="Last API Start Time",
        readonly=True,
    )
    indiamart_last_end_time = fields.Datetime(
        string="Last API End Time",
        readonly=True,
    )

    # ── helpers ──────────────────────────────────────────────

    def _get_indiamart_config(self):
        """Return the singleton indiamart.config record."""
        config = self.env['indiamart.config'].search([], limit=1)
        if not config:
            config = self.env['indiamart.config'].create({})
        return config

    def get_values(self):
        res = super().get_values()
        config = self._get_indiamart_config()
        res.update(
            indiamart_active=config.is_active,
            indiamart_api_key=config.api_key,
            indiamart_api_base_url=config.api_base_url,
            indiamart_is_mock_server=config.is_mock_server,
            indiamart_key_generated_date=config.key_generated_date,
            indiamart_historical_sync_done=config.historical_sync_done,
            indiamart_historical_sync_cursor=config.historical_sync_cursor,
            indiamart_last_sync_datetime=config.last_sync_datetime,
            indiamart_last_start_time=config.last_start_time,
            indiamart_last_end_time=config.last_end_time,
        )
        return res

    def set_values(self):
        super().set_values()
        config = self._get_indiamart_config()
        config.write({
            'is_active': self.indiamart_active,
            'api_key': self.indiamart_api_key,
            'api_base_url': self.indiamart_api_base_url,
            'is_mock_server': self.indiamart_is_mock_server,
            'key_generated_date': self.indiamart_key_generated_date,
        })
