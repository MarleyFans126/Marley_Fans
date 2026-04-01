from odoo import models, fields, api

class WhatsAppTemplate(models.Model):
    _name = 'whatsapp.template'
    _description = 'WhatsApp Template'

    name = fields.Char(string='Internal Name', required=True)
    template_name = fields.Char(string='Template Name', required=True, help='Exact Meta Template Name')
    language_code = fields.Char(string='Language Code', default='en_US', required=True, help="Must match Meta exactly e.g. en_US or en")
    category = fields.Selection([
        ('marketing', 'Marketing'),
        ('utility', 'Utility'),
        ('authentication', 'Authentication')
    ], string='Category', required=True)
    header_type = fields.Selection([
        ('none', 'None'),
        ('text', 'Text'),
        ('image', 'Image'),
        ('document', 'Document'),
    ], string='Header Type', default='none', required=True)
    header_text = fields.Char(string='Header Text')
    body_text = fields.Text(string='Body Text', required=True)
    footer_text = fields.Text(string='Footer Text')
    variable_count = fields.Integer(string='Variable Count', default=0)
    active = fields.Boolean(string='Active', default=True)

    button_ids = fields.One2many(
        'whatsapp.template.button',
        'template_id',
        string="Buttons"
    )
    variable_ids = fields.One2many(
        'whatsapp.template.variable',
        'template_id',
        string="Variables"
    )

    @api.onchange('body_text')
    def _extract_body_variables(self):
        import re
        for rec in self:
            if not rec.body_text:
                rec.variable_ids = [(5, 0, 0)]
                rec.variable_count = 0
                continue
            
            matches = list(set(re.findall(r'\{\{(\d+)\}\}', rec.body_text)))
            matches.sort(key=int)
            rec.variable_count = len(matches)
            
            existing_vars = {v.variable_key: v for v in rec.variable_ids}
            new_vars = []
            
            for m in matches:
                key = f"{{{{{m}}}}}"
                if key in existing_vars:
                    new_vars.append((4, existing_vars[key].id))
                else:
                    new_vars.append((0, 0, {
                        'variable_key': key,
                        'sample_value': 'Sample',
                        'variable_type': 'free_text',
                    }))
            
            # Use appropriate commands for onchange (replace all with strictly new/kept ones)
            # Actually, just clearing and recreating is safest or carefully managing commands.
            # A simpler approach in onchange for o2m is to assign a new list of command tuples
            commands = [(5, 0, 0)]
            for m in matches:
                key = f"{{{{{m}}}}}"
                if key in existing_vars:
                    commands.append((0, 0, {
                        'variable_key': key,
                        'sample_value': existing_vars[key].sample_value,
                        'variable_type': existing_vars[key].variable_type,
                        'field_name': existing_vars[key].field_name,
                    }))
                else:
                    commands.append((0, 0, {
                        'variable_key': key,
                        'sample_value': 'Sample',
                        'variable_type': 'free_text',
                    }))
            rec.variable_ids = commands

    meta_template_id = fields.Char(string='Meta Template ID', readonly=True)
    meta_status = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('paused', 'Paused'),
        ('disabled', 'Disabled')
    ], string='Meta Status', default='draft', readonly=True)
    rejection_reason = fields.Text(string='Rejection Reason', readonly=True)
    last_synced_on = fields.Datetime(string='Last Synced On', readonly=True)

    def _get_api_config(self):
        config = self.env['whatsapp.service']._get_config()
        if not config.get('business_account_id'):
            from odoo.exceptions import UserError
            raise UserError('WABA ID is not configured. Please check WhatsApp Configuration.')
        return config

    def action_sync_template_status(self):
        """Fetch status for this template individually"""
        self.ensure_one()
        config = self._get_api_config()
        url = f"https://graph.facebook.com/{config['api_version']}/{config['business_account_id']}/message_templates?name={self.template_name}"
        headers = {'Authorization': f"Bearer {config['access_token']}"}
        
        import requests
        try:
            response = requests.get(url, headers=headers, timeout=15)
            data = response.json()
            if response.status_code == 200 and 'data' in data and data['data']:
                template_data = data['data'][0]
                status_mapping = {
                    'APPROVED': 'approved',
                    'PENDING': 'pending',
                    'REJECTED': 'rejected',
                    'PAUSED': 'paused',
                    'DISABLED': 'disabled'
                }
                new_status = status_mapping.get(template_data.get('status', ''), 'draft')
                reason = template_data.get('rejected_reason', '')
                self.write({
                    'meta_status': new_status,
                    'rejection_reason': reason,
                    'meta_template_id': template_data.get('id', self.meta_template_id),
                    'last_synced_on': fields.Datetime.now(),
                })
            elif response.status_code != 200:
                error = data.get('error', {}).get('message', 'Unknown error')
                import logging
                logging.getLogger(__name__).error("Failed to sync template: %s", error)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("Exception syncing template: %s", str(e))

    def action_submit_to_meta(self):
        """Push this template to Meta"""
        self.ensure_one()
        if self.meta_status not in ('draft', 'rejected'):
            from odoo.exceptions import UserError
            raise UserError('Only draft or rejected templates can be submitted.')

        config = self._get_api_config()
        url = f"https://graph.facebook.com/{config['api_version']}/{config['business_account_id']}/message_templates"
        headers = {
            'Authorization': f"Bearer {config['access_token']}",
            'Content-Type': 'application/json'
        }
        
        components = []
        if self.body_text:
            body_comp = {
                'type': 'BODY',
                'text': self.body_text
            }
            if self.variable_ids:
                # Meta expects a list of text examples in consecutive variable order
                # 'example': {'body_text': [['sample1', 'sample2']]}
                sorted_vars = sorted(self.variable_ids, key=lambda v: int(''.join(filter(str.isdigit, v.variable_key))))
                sample_values = [v.sample_value or 'Sample' for v in sorted_vars]
                body_comp['example'] = {'body_text': [sample_values]}
            components.append(body_comp)

        if self.header_type == 'text' and self.header_text:
            components.append({
                'type': 'HEADER',
                'format': 'TEXT',
                'text': self.header_text
            })

        if self.footer_text:
            components.append({
                'type': 'FOOTER',
                'text': self.footer_text
            })
            
        if self.button_ids:
            buttons_payload = []
            for btn in self.button_ids:
                if btn.button_type == 'quick_reply':
                    buttons_payload.append({
                        'type': 'QUICK_REPLY',
                        'text': btn.button_text
                    })
                elif btn.button_type == 'call_phone':
                    buttons_payload.append({
                        'type': 'PHONE_NUMBER',
                        'text': btn.button_text,
                        'phone_number': btn.phone_number
                    })
                elif btn.button_type == 'visit_website':
                    url_comp = {
                        'type': 'URL',
                        'text': btn.button_text,
                        'url': btn.website_url
                    }
                    if btn.url_type == 'dynamic':
                        url_comp['example'] = [btn.website_url.replace('{{1}}', 'example')]
                    buttons_payload.append(url_comp)
            
            components.append({
                'type': 'BUTTONS',
                'buttons': buttons_payload
            })
        
        payload = {
            'name': self.template_name.lower().replace(' ', '_'),
            'language': self.language_code,
            'category': self.category.upper() if self.category else 'MARKETING',
            'components': components
        }

        import requests
        import logging
        try:
            logging.getLogger(__name__).info("Sending Template to Meta: %s", payload)
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            logging.getLogger(__name__).info("Meta Response: %s", response.text)
            
            data = response.json()
            if response.status_code == 200 and 'id' in data:
                self.write({
                    'meta_template_id': data['id'],
                    'meta_status': data.get('status', 'pending').lower(),
                    'last_synced_on': fields.Datetime.now()
                })
            else:
                error = data.get('error', {}).get('message', str(data))
                from odoo.exceptions import UserError
                raise UserError(f'Failed to submit template: {error}')
        except requests.exceptions.Timeout:
            from odoo.exceptions import UserError
            raise UserError('Timeout connecting to Meta.')
        except requests.exceptions.RequestException as e:
            from odoo.exceptions import UserError
            raise UserError(f'Network error: {str(e)}')

    def action_sync_all_templates_from_meta(self):
        config = self._get_api_config()
        base_url = f"https://graph.facebook.com/{config['api_version']}/{config['business_account_id']}/message_templates?limit=100"
        headers = {'Authorization': f"Bearer {config['access_token']}"}
        
        import requests
        import logging
        _logger = logging.getLogger(__name__)
        _logger.info("Starting WhatsApp template sync...")
        
        synced_count = 0
        url = base_url
        
        try:
            while url:
                response = requests.get(url, headers=headers, timeout=30)
                data = response.json()
                
                if response.status_code != 200:
                    error = data.get('error', {}).get('message', 'Unknown error')
                    from odoo.exceptions import UserError
                    raise UserError(f'Sync Failed: {error}')
                
                templates = data.get('data', [])
                for tmpl in templates:
                    _logger.info("Processing template: %s", tmpl.get('name'))
                    existing = self.search([
                        ('template_name', '=', tmpl['name']),
                        ('language_code', '=', tmpl['language'])
                    ], limit=1)
                    
                    status_mapping = {
                        'APPROVED': 'approved',
                        'PENDING': 'pending',
                        'REJECTED': 'rejected',
                        'PAUSED': 'paused',
                        'DISABLED': 'disabled'
                    }
                    new_status = status_mapping.get(tmpl.get('status', '').upper(), 'draft')
                    
                    body_text = ''
                    footer_text = ''
                    header_type = 'none'
                    variable_count = 0
                    
                    for comp in tmpl.get('components', []):
                        if comp['type'] == 'BODY':
                            body_text = comp.get('text', '')
                        elif comp['type'] == 'FOOTER':
                            footer_text = comp.get('text', '')
                        elif comp['type'] == 'HEADER':
                            if comp.get('format') == 'TEXT':
                                header_type = 'text'
                            elif comp.get('format') == 'IMAGE':
                                header_type = 'image'
                            elif comp.get('format') == 'DOCUMENT':
                                header_type = 'document'
                            elif comp.get('format') == 'VIDEO':
                                header_type = 'video'
                    
                    import re
                    if body_text:
                        matches = re.findall(r'\{\{(\d+)\}\}', body_text)
                        if matches:
                            variable_count = max([int(m) for m in matches])
                            
                    vals = {
                        'meta_template_id': tmpl.get('id'),
                        'category': tmpl.get('category', 'MARKETING').lower(),
                        'meta_status': new_status,
                        'rejection_reason': tmpl.get('rejected_reason', ''),
                        'last_synced_on': fields.Datetime.now(),
                        'header_type': header_type,
                        'body_text': body_text,
                        'footer_text': footer_text,
                        'variable_count': variable_count,
                        'active': True, # Explicitly ensure it is active and not hidden
                    }

                    if existing:
                        existing.write(vals)
                    else:
                        vals.update({
                            'name': tmpl['name'].replace('_', ' ').title(),
                            'template_name': tmpl['name'],
                            'language_code': tmpl['language'],
                        })
                        self.create(vals)
                    synced_count += 1
                
                # Pagination
                paging = data.get('paging', {})
                url = paging.get('cursors', {}).get('after') and paging.get('next')
                if not url:
                    break

            _logger.info("Sync complete. Synced %s templates.", synced_count)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Sync Successful',
                    'message': f'Synced {synced_count} templates from Meta.',
                    'type': 'success',
                    'sticky': False,
                    'next': {'type': 'ir.actions.client', 'tag': 'reload'},
                }
            }
        except requests.exceptions.Timeout:
            from odoo.exceptions import UserError
            raise UserError('Timeout connecting to Meta during sync.')
        except Exception as e:
            from odoo.exceptions import UserError
            raise UserError(f'Exception: {str(e)}')

    @api.model
    def cron_sync_pending_templates(self):
        pending = self.search([('meta_status', '=', 'pending')])
        for tmpl in pending:
            tmpl.action_sync_template_status()

class WhatsAppTemplateButton(models.Model):
    _name = 'whatsapp.template.button'
    _description = 'WhatsApp Template Button'

    template_id = fields.Many2one('whatsapp.template', string="Template", required=True, ondelete='cascade')
    button_type = fields.Selection([
        ('quick_reply', 'Quick Reply'),
        ('call_phone', 'Call Phone Number'),
        ('visit_website', 'Visit Website')
    ], string='Type', required=True, default='quick_reply')
    button_text = fields.Char(string='Button Text', required=True)
    phone_number = fields.Char(string='Phone Number')
    website_url = fields.Char(string='Website URL')
    url_type = fields.Selection([
        ('static', 'Static'),
        ('dynamic', 'Dynamic')
    ], string='URL Type', default='static')

    @api.constrains('button_type', 'phone_number', 'website_url', 'template_id')
    def _check_button_constraints(self):
        from odoo.exceptions import ValidationError
        for btn in self:
            if btn.button_type == 'call_phone' and not btn.phone_number:
                raise ValidationError("Phone number is required for 'Call Phone Number' button.")
            if btn.button_type == 'visit_website' and not btn.website_url:
                raise ValidationError("Website URL is required for 'Visit Website' button.")
                
            # Check limits across template
            template_buttons = btn.template_id.button_ids
            if len(template_buttons) > 3:
                raise ValidationError("Maximum 3 buttons allowed per template.")
                
            types_count = {}
            for t_btn in template_buttons:
                types_count[t_btn.button_type] = types_count.get(t_btn.button_type, 0) + 1
                
            if types_count.get('call_phone', 0) > 1:
                raise ValidationError("Only 1 'Call Phone Number' button allows per template.")
            if types_count.get('visit_website', 0) > 2:
                raise ValidationError("Only 2 'Visit Website' buttons allowed per template.")
            
            # Meta mixing rules
            if types_count.get('quick_reply', 0) > 0 and (types_count.get('call_phone', 0) > 0 or types_count.get('visit_website', 0) > 0):
                raise ValidationError("You cannot mix Quick Reply buttons with Call Phone or Visit Website buttons.")

class WhatsAppTemplateVariable(models.Model):
    _name = 'whatsapp.template.variable'
    _description = 'WhatsApp Template Variable'

    template_id = fields.Many2one('whatsapp.template', string="Template", required=True, ondelete='cascade')
    variable_key = fields.Char(string='Variable', required=True)
    sample_value = fields.Char(string='Sample Value', required=True, default='Sample')
    variable_type = fields.Selection([
        ('free_text', 'Free Text'),
        ('field_mapping', 'Model Field')
    ], string='Variable Type', default='free_text', required=True)
    field_name = fields.Char(string='Field Name')
