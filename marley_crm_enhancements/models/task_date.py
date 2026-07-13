from odoo import models, fields, tools


class ProjectTaskDate(models.Model):
    """Read-only SQL view that explodes each Order Booking Form task's key
    dates into one row per date. Lets a single calendar plot two date-types
    side by side — e.g. Scheduled Dispatch vs actual Dispatch — each event
    labelled and colour-coded by which date it is. Always in sync with the
    task (it's a view, no data to maintain)."""
    _name = 'project.task.date'
    _description = 'Order Booking Form Key Dates'
    _auto = False
    _order = 'date'
    _rec_name = 'name'

    task_id = fields.Many2one('project.task', string='Order Booking Form', readonly=True)
    name = fields.Char(readonly=True)
    company_name = fields.Char(string='Company', readonly=True)
    date = fields.Date(string='Date', readonly=True)
    date_type = fields.Selection([
        ('dispatch_scheduled', 'Scheduled Dispatch'),
        ('dispatch_actual', 'Dispatch Date'),
        ('install_scheduled', 'Scheduled Installation'),
        ('install_completed', 'Installation Completed'),
    ], string='Date Type', readonly=True)
    category = fields.Selection([
        ('dispatch', 'Dispatch'),
        ('install', 'Installation'),
    ], string='Category', readonly=True)
    stage_id = fields.Many2one('project.task.type', string='Stage', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE VIEW {table} AS (
                SELECT t.id * 10 + 1 AS id, t.id AS task_id,
                       'Scheduled Dispatch — ' || COALESCE(NULLIF(t.inst_company_name, ''), t.name, 'Task') AS name,
                       t.inst_company_name AS company_name,
                       t.inst_scheduled_dispatch_date AS date,
                       'dispatch_scheduled' AS date_type, 'dispatch' AS category,
                       t.stage_id AS stage_id
                  FROM project_task t
                 WHERE t.inst_scheduled_dispatch_date IS NOT NULL
                UNION ALL
                SELECT t.id * 10 + 2, t.id,
                       'Dispatch Date — ' || COALESCE(NULLIF(t.inst_company_name, ''), t.name, 'Task'),
                       t.inst_company_name, t.date_deadline::date,
                       'dispatch_actual', 'dispatch', t.stage_id
                  FROM project_task t
                 WHERE t.date_deadline IS NOT NULL
                UNION ALL
                SELECT t.id * 10 + 3, t.id,
                       'Scheduled Installation — ' || COALESCE(NULLIF(t.inst_company_name, ''), t.name, 'Task'),
                       t.inst_company_name, t.inst_installation_date,
                       'install_scheduled', 'install', t.stage_id
                  FROM project_task t
                 WHERE t.inst_installation_date IS NOT NULL
                UNION ALL
                SELECT t.id * 10 + 4, t.id,
                       'Installation Completed — ' || COALESCE(NULLIF(t.inst_company_name, ''), t.name, 'Task'),
                       t.inst_company_name, t.inst_completed_date,
                       'install_completed', 'install', t.stage_id
                  FROM project_task t
                 WHERE t.inst_completed_date IS NOT NULL
            )
        """.format(table=self._table))
