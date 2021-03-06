# -*- coding: utf-8 -*-
from openerp import models, fields, api


class instance_host(models.Model):

    """"""

    _name = 'infrastructure.instance_host'
    _description = 'instance_host'

    server_hostname_id = fields.Many2one(
        'infrastructure.server_hostname',
        string='Server Hostname',
        required=True
        )
    subdomain = fields.Char(
        string='Subdomain'
        )
    instance_id = fields.Many2one(
        'infrastructure.instance',
        string='instance_id',
        ondelete='cascade',
        required=True
        )
    prefix = fields.Char(
        'Prefix',
        required=False,
        )
    name = fields.Char(
        'Name',
        compute='get_name',
        store=True,
        )
    server_id = fields.Many2one(
        'infrastructure.server',
        string='Server',
        related='instance_id.environment_id.server_id',
        store=True,
        readonly=True
        )
    type = fields.Selection(
        [('main', 'Main'),
         ('redirect_to_main', 'Redirect To Main'),
         ('other', 'Other')],
        string='Main?',
        default='main',
        )
    wildcard = fields.Boolean(
        string='Wildcard',
        related='server_hostname_id.wildcard'
        )

    _sql_constraints = [
        ('name_uniq', 'unique(name, server_id)',
            'Name must be unique per server!'),
    ]

    @api.one
    @api.depends('prefix', 'server_hostname_id.name')
    def get_name(self):
        name = self.server_hostname_id.name
        if self.prefix and name and self.server_hostname_id.wildcard:
            name = self.prefix + '.' + name
        self.name = name

    @api.onchange('subdomain')
    def _change_subdomain(self):
        prefix = False
        if self.subdomain:
            prefix = self.subdomain
        if self.instance_id.database_type_id.url_prefix:
            if prefix:
                prefix = self.instance_id.database_type_id.url_prefix + '_' + prefix
            else:
                prefix = self.instance_id.database_type_id.url_prefix
        self.prefix = prefix

    @api.onchange('server_hostname_id', 'instance_id')
    def _get_name(self):
        if not self.server_hostname_id:
            server_hostname = self.env[
                'infrastructure.server_hostname'].search(
                    [('server_id', '=', self.instance_id.server_id.id)],
                    limit=1)
            self.server_hostname_id = server_hostname.id
        if self.server_hostname_id.wildcard:
            if not self.subdomain:
                self.subdomain = self.instance_id.environment_id.name
        else:
            self.subdomain = False
        self._change_subdomain()
