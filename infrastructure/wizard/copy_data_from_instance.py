# -*- coding: utf-8 -*-
from openerp import fields, api, _
from openerp.osv import osv
from openerp.exceptions import Warning


class infrastructure_copy_data_from_instance(osv.osv_memory):
    _name = "infrastructure.copy_data_from_instance.wizard"
    _description = "Infrastructure Copy Data From Instance Wizard"

    @api.model
    def get_target_instance(self):
        return self.env['infrastructure.instance'].browse(
            self.env.context.get('active_id', False))

    source_instance_id = fields.Many2one(
        'infrastructure.instance',
        'Source Instance',
        required=True,
        domain="[('server_id','=',server_id),('id','!=',target_instance_id),('state', '=', 'active')]",
        )
    server_id = fields.Many2one(
        'infrastructure.server',
        'Server',
        compute='get_server_and_source_instance',
        )
    target_instance_id = fields.Many2one(
        'infrastructure.instance',
        'Source Instance',
        readonly=True,
        required=True,
        default=get_target_instance,
        )

    @api.one
    @api.depends('target_instance_id')
    def get_server_and_source_instance(self):
        self.server_id = self.target_instance_id.server_id
        self.source_instance_id = self.env['infrastructure.instance'].search(
            [('environment_id', '=', self.target_instance_id.environment_id.id),
                ('id', '!=', self.target_instance_id.id)],
            limit=1)

    @api.multi
    def action_confirm(self):
        self.ensure_one()
        return self.target_instance_id.copy_databases_from(
            self.source_instance_id)
