from markupsafe import Markup
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    # ------------------------------------------------------------------
    # Database init — clean up duplicate stages from initial install
    # ------------------------------------------------------------------

    def init(self):
        """
        Remove duplicate CRM stages that were created by the initial
        module install (which used custom XML IDs instead of referencing
        the existing Odoo default stages).

        Mapping:
            marley_crm_enhancements.stage_new         → crm.stage_lead1 (New)
            marley_crm_enhancements.stage_qualify      → crm.stage_lead2 (Qualify)
            marley_crm_enhancements.stage_proposition  → crm.stage_lead3 (Proposition)
            marley_crm_enhancements.stage_won          → crm.stage_lead4 (Won)
        """
        mapping = {
            'stage_new': 'stage_lead1',
            'stage_qualify': 'stage_lead2',
            'stage_proposition': 'stage_lead3',
            'stage_won': 'stage_lead4',
        }

        for dup_xmlid, orig_xmlid in mapping.items():
            # Fetch duplicate record ID (created by our module)
            self.env.cr.execute("""
                SELECT res_id FROM ir_model_data
                WHERE module = 'marley_crm_enhancements'
                  AND name = %s
                  AND model = 'crm.stage'
            """, (dup_xmlid,))
            dup_row = self.env.cr.fetchone()

            # Fetch original Odoo stage record ID
            self.env.cr.execute("""
                SELECT res_id FROM ir_model_data
                WHERE module = 'crm'
                  AND name = %s
                  AND model = 'crm.stage'
            """, (orig_xmlid,))
            orig_row = self.env.cr.fetchone()

            if dup_row and orig_row and dup_row[0] != orig_row[0]:
                dup_id = dup_row[0]
                orig_id = orig_row[0]

                _logger.info(
                    "Cleaning up duplicate CRM stage: %s (ID %s) → original (ID %s)",
                    dup_xmlid, dup_id, orig_id,
                )

                # Reassign leads from the duplicate stage to the original
                self.env.cr.execute(
                    "UPDATE crm_lead SET stage_id = %s WHERE stage_id = %s",
                    (orig_id, dup_id),
                )

                # Delete the duplicate stage record
                self.env.cr.execute(
                    "DELETE FROM crm_stage WHERE id = %s", (dup_id,)
                )

                # Remove the stale ir_model_data entry
                self.env.cr.execute("""
                    DELETE FROM ir_model_data
                    WHERE module = 'marley_crm_enhancements'
                      AND name = %s
                      AND model = 'crm.stage'
                """, (dup_xmlid,))

    project_id = fields.Many2one(
        'project.project',
        string='Project',
        readonly=True,
        copy=False,
        help='Project created when lead is marked as Won.',
    )

    project_count = fields.Integer(
        string='Task Count',
        compute='_compute_project_count',
    )

    def _compute_project_count(self):
        has_task_model = 'project.task' in self.env
        for lead in self:
            if not has_task_model or not lead.id:
                lead.project_count = 0
                continue
            lead.project_count = self.env['project.task'].sudo().search_count(
                [('lead_id', '=', lead.id)]
            )

    @api.model
    def _get_installation_project(self):
        """Return the singleton 'Installation' project, creating it if needed."""
        Project = self.env['project.project'].sudo()
        project = Project.search([('name', '=', 'Installation')], limit=1)
        if project:
            return project
        stage_xmlids = [
            'marley_crm_enhancements.project_stage_installation',
            'marley_crm_enhancements.project_stage_in_progress',
            'marley_crm_enhancements.project_stage_done',
            'marley_crm_enhancements.project_stage_cancelled',
        ]
        stages = []
        for xmlid in stage_xmlids:
            s = self.env.ref(xmlid, raise_if_not_found=False)
            if s:
                stages.append(s.id)
        return Project.create({
            'name': 'Installation',
            'type_ids': [(6, 0, stages)] if stages else False,
        })

    def action_view_project(self):
        """Open installation tasks linked to this lead."""
        self.ensure_one()
        tasks = self.env['project.task'].sudo().search([('lead_id', '=', self.id)])
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Installation Tasks'),
            'res_model': 'project.task',
            'domain': [('lead_id', '=', self.id)],
            'context': {
                'default_lead_id': self.id,
                'default_partner_id': self.partner_id.id if self.partner_id else False,
                'default_project_id': self._get_installation_project().id,
            },
        }
        if len(tasks) == 1:
            action.update({'view_mode': 'form', 'res_id': tasks.id})
        else:
            action['view_mode'] = 'list,form'
        return action

    # ------------------------------------------------------------------
    # Won Conversion: Lead → Customer + Sales Order + Project
    # ------------------------------------------------------------------

    def action_convert_to_won(self):
        """
        Called when a lead is marked as Won.
        Creates: res.partner (customer), project.project linked to customer & SO.
        The Sales Order is expected to already exist (created from Proposition stage).
        """
        self.ensure_one()
        _logger.info("Won conversion started for Lead %s (%s)", self.id, self.name)

        # Step 1: Create or find customer (res.partner)
        partner = self._find_or_create_customer()

        # Step 2: Link partner to lead
        if partner and not self.partner_id:
            self.partner_id = partner

        # Step 3: Link existing quotations/SOs to the partner
        self._link_quotations_to_partner(partner)

        # Step 4: Get all linked sale orders
        sale_orders = self.env['sale.order'].sudo().search([
            ('opportunity_id', '=', self.id),
        ])

        # Step 5: Log in chatter (project is created manually via "Create Project" button)
        so_names = ', '.join(sale_orders.mapped('name')) if sale_orders else 'None'
        is_manual = self._context.get('skip_won_status')
        title = "Lead Conversion" if is_manual else "Lead Won — Conversion Summary"

        body = Markup("<b>%s</b><br/>") % title
        if partner:
            body += Markup("Customer: %s<br/>") % partner.name
        if sale_orders:
            body += Markup("Sales Orders: %s<br/>") % so_names
        self.message_post(body=body)

        # Step 6: Internal notification only (no client email — handled by Automated Action)
        if not is_manual:
            self._notify_won_internal(partner, None, sale_orders)

        _logger.info(
            "Won conversion done for Lead %s | partner=%s | SOs=%s",
            self.id,
            partner.id if partner else None,
            sale_orders.ids if sale_orders else [],
        )
        return True

    def _find_or_create_customer(self):
        """Find existing partner by email/phone or create a new one."""
        self.ensure_one()

        # Try to find existing partner
        domain = []
        if self.email_from:
            domain = [('email', '=ilike', self.email_from)]
        if not domain and self.phone:
            domain = [('phone', 'ilike', self.phone[-10:])]

        partner = False
        if domain:
            partner = self.env['res.partner'].sudo().search(domain, limit=1)

        if partner:
            _logger.info("Existing partner found: %s (ID %s)", partner.name, partner.id)
            return partner

        # Create new partner
        vals = {
            'name': self.partner_name or self.contact_name or self.name,
            'email': self.email_from,
            'phone': self.phone,
            'street': self.street,
            'city': self.city,
            'state_id': self.state_id.id if self.state_id else False,
            'country_id': self.country_id.id if self.country_id else False,
            'zip': self.zip,
            'company_type': 'company' if self.partner_name else 'person',
            'customer_rank': 1,
        }
        # Add contact person as child if company
        partner = self.env['res.partner'].sudo().create(vals)
        _logger.info("New customer created: %s (ID %s)", partner.name, partner.id)

        # If we have both company name and contact name, create a contact under the company
        if self.partner_name and self.contact_name and self.partner_name != self.contact_name:
            self.env['res.partner'].sudo().create({
                'name': self.contact_name,
                'parent_id': partner.id,
                'type': 'contact',
                'email': self.email_from,
                'phone': self.phone,
            })

        return partner

    def _create_project(self, partner, sale_orders=None):
        """Create a project linked to the customer and sales orders."""
        self.ensure_one()
        if not partner:
            return False

        project_name = "%s - %s" % (self.name, partner.name)

        # Build description with SO references
        desc_parts = []
        if self.description:
            desc_parts.append(self.description)
        if sale_orders:
            desc_parts.append("Sales Orders: %s" % ', '.join(sale_orders.mapped('name')))
        description = '\n'.join(desc_parts)

        project_vals = {
            'name': project_name,
            'partner_id': partner.id,
            'description': description,
            'lead_id': self.id,
            'site_contact_person': self.contact_name or '',
            'site_contact_number': self.phone or '',
        }

        project = self.env['project.project'].sudo().create(project_vals)
        _logger.info("Project created: %s (ID %s)", project.name, project.id)

        # Auto-create Installation task with "Installation" stage
        installation_stage = self.env.ref(
            'marley_crm_enhancements.project_stage_installation', raise_if_not_found=False
        )
        task_vals = {
            'name': 'Installation',
            'project_id': project.id,
            'partner_id': partner.id,
            'description': description,
        }
        if installation_stage:
            task_vals['stage_id'] = installation_stage.id
        if sale_orders:
            task_vals['sale_order_id'] = sale_orders[0].id
        self.env['project.task'].sudo().create(task_vals)

        # Link sale orders to this project (if sale_project module provides the field)
        if sale_orders:
            for order in sale_orders:
                if hasattr(order, 'project_id'):
                    order.sudo().write({'project_id': project.id})

        return project

    def _link_quotations_to_partner(self, partner):
        """Link any existing quotations/SOs on this lead to the partner."""
        self.ensure_one()
        if not partner:
            return
        orders = self.env['sale.order'].sudo().search([
            ('opportunity_id', '=', self.id),
            ('partner_id', '=', False),
        ])
        if orders:
            orders.write({'partner_id': partner.id})

    # ------------------------------------------------------------------
    # Won: Internal notifications to sales team + management
    # ------------------------------------------------------------------

    def _notify_won_internal(self, partner, project, sale_orders):
        """Send internal notification to sales team and management on Won."""
        self.ensure_one()

        so_names = ', '.join(sale_orders.mapped('name')) if sale_orders else 'N/A'
        revenue = self.expected_revenue or 0

        subject = "Lead Won: %s" % self.name
        body = Markup(
            "<b>A lead has been marked as Won!</b><br/><br/>"
            "<b>Lead:</b> %(lead)s<br/>"
            "<b>Customer:</b> %(customer)s<br/>"
            "<b>Expected Revenue:</b> %(revenue)s<br/>"
            "<b>Sales Orders:</b> %(orders)s<br/>"
            "<b>Project:</b> %(project)s<br/>"
            "<b>Salesperson:</b> %(salesperson)s<br/>"
        ) % {
            'lead': self.name,
            'customer': partner.name if partner else 'N/A',
            'revenue': '{:,.0f}'.format(revenue),
            'orders': so_names,
            'project': project.name if project else 'N/A',
            'salesperson': self.user_id.name if self.user_id else 'N/A',
        }

        # Collect recipients: salesperson + sales manager + all CRM managers
        partner_ids = []

        # Salesperson
        if self.user_id and self.user_id.partner_id:
            partner_ids.append(self.user_id.partner_id.id)

        # Sales team leader
        if self.team_id and self.team_id.user_id and self.team_id.user_id.partner_id:
            partner_ids.append(self.team_id.user_id.partner_id.id)

        # CRM Sales Manager group
        try:
            manager_group = self.env.ref('sales_team.group_sale_manager', raise_if_not_found=False)
            if manager_group:
                for user in manager_group.users:
                    if user.partner_id.id not in partner_ids:
                        partner_ids.append(user.partner_id.id)
        except Exception:
            pass

        if partner_ids:
            # Remove duplicates
            partner_ids = list(set(partner_ids))
            try:
                self.message_notify(
                    partner_ids=partner_ids,
                    subject=subject,
                    body=body,
                    message_type='comment',
                )
                _logger.info("Won notification sent to %d recipients for Lead %s", len(partner_ids), self.id)
            except Exception as e:
                _logger.warning("Failed to send Won notification for Lead %s: %s", self.id, e)

    # ------------------------------------------------------------------
    # Won: Client email is now handled by Automated Action ('won stage' template)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Override Won action to trigger conversion
    # ------------------------------------------------------------------

    def action_set_won_rainbowman(self):
        """Override to run customer/project conversion before marking won."""
        for lead in self:
            lead.action_convert_to_won()
        return super().action_set_won_rainbowman()

    # ------------------------------------------------------------------
    # Create Quotation from Lead
    # ------------------------------------------------------------------

    def action_create_project(self):
        """Open a new installation task form pre-filled from this lead.
        The task is added to the shared singleton 'Installation' project.
        """
        self.ensure_one()

        partner = self.partner_id
        if not partner:
            partner = self._find_or_create_customer()
            self.partner_id = partner

        project = self._get_installation_project()
        install_stage = self.env.ref(
            'marley_crm_enhancements.project_stage_installation',
            raise_if_not_found=False,
        )

        return {
            'type': 'ir.actions.act_window',
            'name': _('New Installation Task'),
            'res_model': 'project.task',
            'view_mode': 'form',
            'context': {
                'default_name': self.name or '',
                'default_project_id': project.id,
                'default_partner_id': partner.id if partner else False,
                'default_lead_id': self.id,
                'default_stage_id': install_stage.id if install_stage else False,
                'default_is_installation': True,
                'default_inst_site_contact': self.contact_name or '',
                'default_inst_site_phone': self.phone or '',
            },
            'target': 'current',
        }

    def action_create_quotation(self):
        """Open a new sale.order form pre-filled from this lead."""
        self.ensure_one()

        # Find or create partner for the quotation
        partner = self.partner_id
        if not partner:
            partner = self._find_or_create_customer()
            self.partner_id = partner

        return {
            'type': 'ir.actions.act_window',
            'name': _('New Quotation'),
            'res_model': 'sale.order',
            'view_mode': 'form',
            'context': {
                'default_partner_id': partner.id if partner else False,
                'default_opportunity_id': self.id,
                'default_origin': self.name,
                'default_campaign_id': self.campaign_id.id if self.campaign_id else False,
                'default_source_id': self.source_id.id if self.source_id else False,
            },
            'target': 'current',
        }
