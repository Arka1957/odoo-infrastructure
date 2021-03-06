# -*- coding: utf-8 -*-
from openerp import models, fields, api, SUPERUSER_ID, _
from openerp.exceptions import except_orm
import xmlrpclib
import socket
from dateutil.relativedelta import relativedelta
from datetime import datetime
from .server import custom_sudo as sudo
from fabric.contrib.files import exists, append, sed
from erppeek import Client
from openerp.exceptions import Warning
from ast import literal_eval
import os
import base64
import requests
import simplejson
import logging
_logger = logging.getLogger(__name__)


class database(models.Model):

    """"""
    _name = 'infrastructure.database'
    _description = 'database'
    _inherit = ['ir.needaction_mixin', 'mail.thread']
    _states_ = [
        ('draft', 'Draft'),
        ('maintenance', 'Maintenance'),
        ('active', 'Active'),
        ('deactivated', 'Deactivated'),
        ('cancel', 'Cancel'),
    ]

    _mail_post_access = 'read'

    @api.model
    def _get_base_modules(self):
        base_modules = self.env['infrastructure.base.module'].search([
            ('default_on_new_db', '=', True)])
        return [(6, _, base_modules.ids)]

    database_type_id = fields.Many2one(
        'infrastructure.database_type',
        string='Database Type',
        readonly=True,
        required=True,
        states={'draft': [('readonly', False)]},
        track_visibility='onchange',
        copy=False,
        )
    name = fields.Char(
        string='Name',
        required=True,
        readonly=True,
        states={'draft': [('readonly', False)]},
        track_visibility='onchange'
        )
    color = fields.Integer(
        string='Color Index',
        compute='get_color',
        )
    partner_id = fields.Many2one(
        'res.partner',
        string='Partner',
        required=True,
        )
    demo_data = fields.Boolean(
        string='Demo Data?',
        readonly=True,
        states={'draft': [('readonly', False)]},
        )
    note = fields.Html(
        string='Note'
        )
    smtp_server_id = fields.Many2one(
        'infrastructure.mailserver',
        string='SMTP Server',
        )
    domain_alias = fields.Char(
        string='Domain Alias',
        compute='get_domain_alias',
        )
    attachment_loc_type = fields.Selection(
        [(u'filesystem', 'filesystem'), (u'database', 'database')],
        string='Attachment Location Type',
        default='filesystem',
        readonly=True,
        states={'draft': [('readonly', False)]},
        )
    attachment_location = fields.Char(
        string='Attachment Location',
        readonly=True,
        states={'draft': [('readonly', False)]},
        )
    issue_date = fields.Date(
        string='Issue Data',
        copy=False,
        default=fields.Date.context_today,
        )
    deactivation_date = fields.Date(
        string='Deactivation Date',
        copy=False,
        help='Depending on type it could be onl informative or could be automatically deactivated on this date',
        )
    drop_date = fields.Date(
        string='Drop Date',
        copy=False,
        help='Depending on type it could be onl informative or could be automatically dropped on this date',
        )
    advance_type = fields.Selection(
        related='database_type_id.type',
        string='Type',
        readonly=True,
        store=True,
        )
    state = fields.Selection(
        _states_,
        'State',
        default='draft'
        )
    instance_id = fields.Many2one(
        'infrastructure.instance',
        string='Instance',
        ondelete='cascade',
        readonly=True,
        states={'draft': [('readonly', False)]},
        required=True,
        )
    environment_id = fields.Many2one(
        'infrastructure.environment',
        string='Environment',
        related='instance_id.environment_id',
        store=True,
        readonly=True,
        )
    server_id = fields.Many2one(
        'infrastructure.server',
        string='Server',
        related='instance_id.environment_id.server_id',
        store=True,
        readonly=True,
        )
    main_hostname = fields.Char(
        string='Main Hostname',
        compute='get_main_hostname',
        )
    backup_ids = fields.One2many(
        'infrastructure.database.backup',
        'database_id',
        string='Backups',
        readonly=True,
        )
    module_ids = fields.One2many(
        'infrastructure.database.module',
        'database_id',
        string='Modules',
        )
    base_module_ids = fields.Many2many(
        'infrastructure.base.module',
        'infrastructure_database_ids_base_module_rel',
        'database_id',
        'base_module_id',
        string='Base Modules',
        default=_get_base_modules,
        )
    admin_password = fields.Char(
        string='Admin Password',
        help='When trying to connect to the database first we are going to try by using the instance password and then with thisone.',
        readonly=True,
        required=True,
        states={'draft': [('readonly', False)]},
        )
    virtual_alias = fields.Char(
        string='Virtual Alias',
        compute='get_aliases',
        )
    local_alias = fields.Char(
        string='Local Alias',
        compute='get_aliases',
        )
    mailgate_path = fields.Char(
        string='Mailgate Path',
        compute='get_mailgate_path',
        )
    alias_prefix = fields.Char(
        'Alias Prefix',
        copy=False,
        )
    alias_hostname_id = fields.Many2one(
        'infrastructure.server_hostname',
        string='Alias Hostname',
        copy=False,
        )
    alias_hostname_wildcard = fields.Boolean(
        related='alias_hostname_id.wildcard',
        string='Wildcard?',
        readonly=True,
        copy=False,
        )
    module_count = fields.Integer(
        string='# Modules',
        compute='_get_modules',
        )
    daily_backup = fields.Boolean(
        string='Daily Backups?',
        )
    weekly_backup = fields.Boolean(
        string='Weekly Backups?',
        )
    monthly_backup = fields.Boolean(
        string='Monthly Backups?',
        )
    backups_enable = fields.Boolean(
        'Backups Enable',
        copy=False,
        )
    catchall_enable = fields.Boolean(
        'Catchall Enable',
        copy=False,
        )

    @api.one
    @api.depends('state')
    def get_color(self):
        color = 4
        if self.state == 'draft':
            color = 7
        elif self.state == 'cancel':
            color = 1
        self.color = color

    @api.onchange('instance_id')
    def _onchange_instance(self):
        instance = self.instance_id
        self.partner_id = instance.environment_id.partner_id
        self.database_type_id = instance.database_type_id
        if instance.main_hostname_id:
            self.alias_hostname_id = instance.main_hostname_id.server_hostname_id
            self.alias_prefix = instance.main_hostname_id.prefix

    @api.one
    @api.depends(
        'instance_id.main_hostname',
        'instance_id.db_filter.add_bd_name_to_host'
         )
    def get_main_hostname(self):
        main_hostname = self.instance_id.main_hostname
        if self.instance_id.db_filter.add_bd_name_to_host:
            main_hostname = "%s.%s" % (
                self.name,
                self.instance_id.main_hostname_id.name
                )
        self.main_hostname = main_hostname

    @api.one
    @api.depends('module_ids')
    def _get_modules(self):
        self.module_count = len(self.module_ids)

    @api.one
    @api.depends(
        'alias_prefix', 'alias_hostname_id', 'alias_hostname_id.wildcard')
    def get_domain_alias(self):
        domain_alias = False
        if self.alias_hostname_id:
            domain_alias = ''
            if self.alias_hostname_id.wildcard and self.alias_prefix:
                domain_alias = self.alias_prefix + '.'
            domain_alias += self.alias_hostname_id.name
        self.domain_alias = domain_alias

    @api.one
    @api.depends('instance_id')
    def get_mailgate_path(self):
        """We use this function because perhups in future you need to use one
        or another mailgate file depending odoo version
        """
        mailgate_path = self.server_id.mailgate_file
        self.mailgate_path = mailgate_path

    @api.one
    @api.depends('virtual_alias', 'local_alias', 'instance_id')
    def get_aliases(self):
        virtual_alias = False
        local_alias = False
        self.virtual_alias = virtual_alias
        self.local_alias = local_alias
        if self.domain_alias:
            virtual_alias = "@%s %s@localhost" % (
                self.domain_alias, self.domain_alias)
            local_alias = self.get_local_alias()
        self.virtual_alias = virtual_alias
        self.local_alias = local_alias

    @api.model
    def get_local_alias(self):
        local_alias = False
        if self.mailgate_path:
            local_alias = '%s: "| %s  --host=localhost --port=%i -u %i -p %s -d %s' % (
                self.domain_alias, self.mailgate_path,
                self.instance_id.xml_rpc_port,
                SUPERUSER_ID, self.instance_id.admin_pass, self.name)
        return local_alias

    _sql_constraints = [
        ('name_uniq', 'unique(name, instance_id)',
            'Database Name Must be Unique per instance'),
    ]

    @api.one
    def unlink(self):
        if self.state not in ('draft', 'cancel'):
            raise Warning(
                _('You cannot delete a database which is not draft \
                    or cancelled.'))
        return super(database, self).unlink()

    @api.onchange('database_type_id', 'instance_id')
    def onchange_database_type_id(self):
        if self.database_type_id and self.instance_id:
            self.name = ('%s_%s') % (
                self.database_type_id.prefix,
                self.instance_id.environment_id.name.replace('-', '_')
                    )
            self.admin_password = self.database_type_id.db_admin_pass or self.instance_id.name

    @api.onchange('database_type_id', 'issue_date')
    def get_deact_date(self):
        deactivation_date = False
        drop_date = False
        if self.issue_date:
            if self.database_type_id.auto_deactivation_days:
                deactivation_date = (datetime.strptime(
                    self.issue_date, '%Y-%m-%d') + relativedelta(
                    days=self.database_type_id.auto_deactivation_days))
            if self.database_type_id.auto_drop_days:
                drop_date = (datetime.strptime(
                    self.issue_date, '%Y-%m-%d') + relativedelta(
                    days=self.database_type_id.auto_drop_days))
        self.deactivation_date = deactivation_date
        self.drop_date = drop_date

    @api.one
    def show_passwd(self):
        raise except_orm(
            _("Password:"),
            _("%s") % self.admin_password
            )

# DATABASE CRUD

    @api.multi
    def get_sock(self, service='db', max_attempts=5):
        self.ensure_one()
        base_url = self.instance_id.main_hostname
        rpc_db_url = '%s/xmlrpc/%s' % (base_url, service)
        # rpc_db_url = 'http://%s/xmlrpc/%s' % (base_url, service)
        sock = xmlrpclib.ServerProxy(rpc_db_url)

        # try connection
        connected = False
        attempts = 0
        while not connected and attempts < max_attempts:
            attempts += 1
            _logger.info("Connecting, attempt number: %i" % attempts)
            try:
                sock._()   # Call a fictive method.
            except xmlrpclib.Fault:
                # connected to the server and the method doesn't exist which is expected.
                _logger.info("Connected to socket")
                connected = True
                pass
            except socket.error:
                _logger.info("Could not connect to socket")
                pass
            except:
                # Tuve que agregar este porque el error no me era atrapado arriba
                _logger.info("Connecting3")
                pass
        if not connected:
            raise Warning(_("Could not connect to socket '%s'") % (rpc_db_url))
        return sock

    @api.one
    def create_db(self):
        """Funcion que utliza erpeek para crear bds"""
        _logger.info("Creating db '%s'" % (self.name))
        client = self.get_client(not_database=True)
        lang = self.database_type_id.install_lang_id or 'en_US'
        client.create_database(
            self.instance_id.admin_pass,
            self.name,
            demo=self.demo_data,
            lang=lang,
            user_password=self.admin_password or 'admin')
        client = self.get_client()
        self.update_modules_data()
        self.install_base_modules()
        self.signal_workflow('sgn_to_active')

    @api.multi
    def drop_db(self):
        """Funcion que utiliza ws nativos de odoo para eliminar db"""
        self.ensure_one()
        if self.advance_type == 'protected':
            raise Warning(_('You can not drop a database protected,\
                you can change database type, or drop it manually'))
        _logger.info("Dropping db '%s'" % (self.name))
        sock = self.get_sock()
        try:
            sock.drop(self.instance_id.admin_pass, self.name)
        except:
            # If we get an error we try restarting the service
            try:
                self.instance_id.start_odoo_service()
                # we ask again for sock and try to connect waiting for service start
                sock = self.get_sock(max_attempts=1000)
                sock.drop(self.instance_id.admin_pass, self.name)
            except Exception, e:
                raise Warning(
                    _('Unable to drop Database. If you are working in an \
                    instance with "workers" then you can try \
                    restarting service. This is what we get:\n%s') % (e))
        self.signal_workflow('sgn_cancel')

    @api.one
    def action_backup_now(self):
        client = self.get_client()
        try:
            self_db_id = client.model('ir.model.data').xmlid_to_res_id(
                'database_tools.db_self_database')
            res = client.model('db.database').action_database_backup(self_db_id)[0]
        except Exception, e:
                raise Warning(_('Could not make backup!\
                    This is what we get %s' % e))
        if res.get('backup_name', False):
            raise Warning(_(
                'Backup %s succesfully created!' % res['backup_name']))
        else:
            raise Warning(_('Could not make backup!\
                This is what we get %s' % res.get('error', '')))

    @api.one
    def migrate_db(self):
        """Funcion que utiliza ws nativos de odoo para hacer update de bd"""
        _logger.info("Migrating db '%s'" % (self.name))
        sock = self.get_sock()
        try:
            return sock.migrate_databases(
                self.instance_id.admin_pass, [self.name])
        except Exception, e:
            raise Warning(
                _('Unable to migrate Database. If you are working in an \
                instance with "workers" then you can try \
                restarting service. This is what we get:\n%s') % (e))

    @api.one
    def rename_db(self, new_name):
        """Funcion que utiliza ws nativos de odoo para hacer update de bd"""
        _logger.info("Rennaming db '%s' to '%s'" % (self.name, new_name))
        sock = self.get_sock()
        try:
            sock.rename(self.instance_id.admin_pass, self.name, new_name)
        except:
            # If we get an error we try restarting the service
            try:
                self.instance_id.start_odoo_service()
                # we ask again for sock and try to connect waiting for start
                sock = self.get_sock(max_attempts=1000)
                sock.rename(self.instance_id.admin_pass, self.name, new_name)
            except Exception, e:
                raise Warning(
                    _('Unable to rename Database. If you are working in an \
                    instance with "workers" then you can try \
                    restarting service. This is what we get:\n%s') % (e))
        self.name = new_name
        # reconfigure catchall
        if self.catchall_enable:
            self.config_catchall()
        if self.backups_enable:
            self.config_backups()

    @api.one
    def exist_db(self, database_name):
        """Funcion que utiliza ws nativos de odoo"""
        sock = self.get_sock()
        if sock.db_exist():
            return True
        else:
            return False

    @api.multi
    def restore(self, file_path, file_name):
        self.ensure_one()
        # TODO podriamos nosotors cambiar workers a 0
        instance = self.instance_id
        new_database_name = self.name
        backups_enable = self.backups_enable
        if instance.workers != 0:
            raise Warning(_('You can not restore a database to a instance with\
                workers, you should first set them to 0, reconfig and try\
                again. After saccesfull restore you can reactivate workers'))
        # TODO ver si hacemos un overwrite si hay que borrarla antes
        # source_server = self.database_id.server_id
        # target_server = instance.server_id
        # remote_server = False
        # if source_server != target_server:
        #     # We use get in target server because using scp is difficult (passing password)
        #     # and also can not use put on source server
        #     remote_server = {
        #         'user_name': source_server.user_name,
        #         'password': source_server.password,
        #         'host_string': source_server.main_hostname,
        #         'port': source_server.ssh_port,
        #     }
        try:
            url = "%s/%s" % (instance.main_hostname, 'restore_db')
            headers = {'content-type': 'application/json'}
            data = {
                "jsonrpc": "2.0",
                "method": "call",
                "params": {
                    'admin_pass': instance.admin_pass,
                    'db_name': new_database_name,
                    'file_path': file_path,
                    'file_name': file_name,
                    'backups_state': backups_enable,
                    # 'remote_server': remote_server,
                    },
            }
            _logger.info('Restoring backup %s, you can also watch target instance log' % new_database_name)
            response = requests.post(
                url,
                data=simplejson.dumps(data),
                headers=headers,
                verify=False, #TODO fix this, we disable verify because an error we have with certificates
                # aca se explica ele error http://docs.python-requests.org/en/latest/community/faq/#what-are-hostname-doesn-t-match-errors
                ).json()
            _logger.info('Restored complete, result: %s' % response)
            if response['result'].get('error', False):
                raise Warning(_(
                    'Unable to restore bd %s, you can try restartin target instance. This is what we get: \n %s') % (
                    new_database_name, response['result'].get('error')))
            _logger.info('Back Up %s Restored Succesfully' % new_database_name)
        except Exception, e:
            raise Warning(_(
                'Unable to restore bd %s, you can try restartin target instance. This is what we get: \n %s') % (
                new_database_name, e))
        _logger.info('Creating new database data on infra')
        self.signal_workflow('sgn_to_active')
        if backups_enable:
            self.config_backups()
        return True

    @api.multi
    def duplicate_db(self, new_database_name, backups_enable, database_type):
        """Funcion que utiliza ws nativos de odoo para hacer duplicar bd"""
        self.ensure_one()
        sock = self.get_sock()
        client = self.get_client()
        new_db = self.copy({
            'name': new_database_name,
            'backups_enable': backups_enable,
            'issue_date': fields.Date.today(),
            'database_type_id': database_type.id,
            })
        try:
            sock.duplicate_database(
                self.instance_id.admin_pass, self.name, new_database_name)
        except:
            # If we get an error we try duplicating restarting service without workers
            try:
                # restart the instance without workers
                instance = self.instance_id
                instance.update_conf_file(force_no_workers=True)
                instance.start_odoo_service()
                # we ask again for sock and try to connect waiting for service start
                sock = self.get_sock(max_attempts=1000)
                sock.duplicate_database(
                    self.instance_id.admin_pass, self.name, new_database_name)
                # client.model('db.database').backups_state(
                #     new_database_name, backups_enable)
                # restart the instance with default config
                instance.update_conf_file()
                instance.start_odoo_service()
                # TODo agregar aca releer los modulos y demas en la nueva bd
            except Exception, e:
                raise Warning(
                    _('Unable to duplicate Database. This is what we get:\n%s') % (e))
        client.model('db.database').backups_state(
            new_database_name, backups_enable)
        new_db.signal_workflow('sgn_to_active')
        if backups_enable:
            new_db.config_backups()
        # devolvemos la accion de la nueva bd creada
        action = self.env['ir.model.data'].xmlid_to_object(
            'infrastructure.action_infrastructure_database_databases')
        if not action:
            return False
        res = action.read()[0]
        # res['domain'] = [('id', 'in', databases.ids)]
        form_view_id = self.env['ir.model.data'].xmlid_to_res_id(
            'infrastructure.view_infrastructure_database_form')
        res['views'] = [(form_view_id, 'form')]
        res['res_id'] = new_db.id
        return res

    # TODO ver si borramos esta Funcion vieja que usaba el kill de odoo tools
    # @api.one
    # def duplicate_db(self, new_database_name, backups_enable):
    #     """Funcion que utiliza ws nativos de odoo para hacer duplicar bd"""
    #     client = self.get_client()
    #     sock = self.get_sock()
    #     new_db = self.copy({
    #         'name': new_database_name,
    #         'backups_enable': backups_enable
    #         })
    #     self.kill_db_connection()
    #     try:
    #         sock.duplicate_database(
    #             self.instance_id.admin_pass, self.name, new_database_name)
    #         client.model('db.database').backups_state(
    #             new_database_name, backups_enable)
    #     except Exception, e:
    #         raise Warning(
    #             _('Unable to duplicate Database. This is what we get:\n%s') % (e))
    #     new_db.signal_workflow('sgn_to_active')
    #     # TODO retornar accion de ventana a la bd creada

    @api.multi
    def get_version(self):
        """Funcion que utiliza ws nativos de odoo"""
        sock = self.get_sock('common')
        return sock.version()

    @api.one
    def kill_db_connection(self):
        client = self.get_client()
        self.server_id.get_env()
        modules = ['database_tools']
        for module in modules:
            if client.modules(name=module, installed=True) is None:
                raise Warning(
                    _("You can not kill connections if module '%s' is not installed in the database") % (module))

        self_db_id = client.model('ir.model.data').xmlid_to_res_id(
            'database_tools.db_self_database')
        client.model('db.database').drop_con(self_db_id)

# Database connection helper
    @api.multi
    def get_client(self, not_database=False):
        self.ensure_one()
        try:
            if not_database:
                return Client(
                    '%s' % (self.instance_id.main_hostname))
                    # 'http://%s' % (self.instance_id.main_hostname))
        except Exception, e:
            raise except_orm(
                _("Unable to Connect to Database."),
                _('Error: %s') % e
                )
        # First try to connect using instance pass
        try:
            return Client(
                '%s' % (self.instance_id.main_hostname),
                # 'http://%s' % (self.instance_id.main_hostname),
                db=self.name,
                user='admin',
                password=self.instance_id.admin_pass)
        # then try to connect using database pass
        except:
            try:
                return Client(
                    '%s' % (self.instance_id.main_hostname),
                    # 'http://%s' % (self.instance_id.main_hostname),
                    db=self.name,
                    user='admin',
                    password=self.admin_password)
            except Exception, e:
                raise except_orm(
                    _("Unable to Connect to Database."),
                    _('Error: %s') % e
                    )

# Backups management

    @api.one
    def update_backups_data(self):
        client = self.get_client()
        modules = ['database_tools']
        for module in modules:
            if client.modules(name=module, installed=True) is None:
                raise Warning(
                    _("You can not Update Backups Data if module '%s' is not installed in the database") % (module))
        self_db_id = client.model('ir.model.data').xmlid_to_res_id(
            'database_tools.db_self_database')
        _logger.info('Updating remote backups data')
        client.model('db.database').update_backups_data(self_db_id)
        _logger.info('Reading Remote Backups Data')
        backups_data = client.read(
            'db.database.backup', [('database_id', '=', self_db_id)])
        imp_fields = [
            'id',
            'database_id/.id',
            'date',
            'name',
            'path',
            'type',
            ]
        rows = []
        for backup in backups_data:
            row = [
                'db_%i_backup_%i' % (self.id, backup['id']),
                self.id,
                backup['date'],
                backup['name'],
                backup['path'],
                backup['type'],
            ]
            rows.append(row)
        self.env['infrastructure.database.backup'].load(imp_fields, rows)
        # remove removed backups
        self_backups = [x.name for x in self.backup_ids]
        remote_backups = [x['name'] for x in backups_data]
        removed_backups = list(set(self_backups) - set(remote_backups))
        self.backup_ids.search([('name', 'in', removed_backups)]).unlink()

# Modules management
    @api.one
    def install_base_modules(self):
        client = self.get_client()
        for module in self.base_module_ids:
            try:
                client.install(module.name)
            except Exception, e:
                _logger.warning(
                    "Unable to install module %s. This is what we get %s." % (
                    module.name, e))
        module_names = [x.name for x in self.base_module_ids]
        self.update_modules_data(
            modules_domain=[('name', 'in', module_names)])

    @api.one
    def action_update_modules_data(self):
        self.update_modules_data(update_list=True)

    def update_modules_data(self, modules_domain=None, update_list=False):
        if not modules_domain:
            modules_domain = []

        client = self.get_client()
        fields = [
            'name',
            'sequence',
            'author',
            'auto_install',
            'installed_version',
            'latest_version',
            'published_version',
            'shortdesc',
            'state']

        module_ids = client.model('ir.module.module').search(modules_domain)

        if update_list:
            client.model('ir.module.module').update_list()

        exp_modules_data = client.model('ir.module.module').read(
            module_ids, fields)

        vals = {'database_id': self.id}

        imp_modules_data = []
        # construimos y agregamos los identificadores al princio
        for exp_module in exp_modules_data:
            # TODO seguro que esto lo podemos hacer mejor con un iterkeys o algo asi
            # simulamos un modulo con el . para hacer un unlink
            module_name = 'infra_db_%i' % 160
            vals = [
                '%s.%s' % (module_name, exp_module['name']),
                self.id,
                exp_module['name'],
                exp_module['sequence'],
                exp_module['author'],
                str(exp_module['auto_install']),
                exp_module['installed_version'],
                exp_module['latest_version'],
                exp_module['published_version'],
                exp_module['shortdesc'],
                exp_module['state'],
                ]
            imp_modules_data.append(vals)
        # LOAD data
        self.env['infrastructure.database.module'].load(
            ['id', 'database_id/.id'] + fields, imp_modules_data, context={'default_noupdate': True})

        # Remove old data only if not modules_domain
        if not modules_domain:
            res = self.env['ir.model.data']._process_end([module_name])
            return res

# MAIL server and catchall configurations
    @api.one
    def upload_mail_server_config(self):
        if not self.smtp_server_id:
            raise Warning(_(
                'You must choose an SMTP server config in order to upload it'))
        rows = [[
            self.smtp_server_id.external_id,
            self.smtp_server_id.name,
            self.smtp_server_id.sequence,
            self.smtp_server_id.smtp_debug,
            self.smtp_server_id.smtp_encryption,
            self.smtp_server_id.smtp_host,
            self.smtp_server_id.smtp_pass,
            self.smtp_server_id.smtp_port,
            self.smtp_server_id.smtp_user,
        ]]
        imp_fields = [
            'id',
            'name',
            'sequence',
            'smtp_debug',
            'smtp_encryption',
            'smtp_host',
            'smtp_pass',
            'smtp_port',
            'smtp_user',
        ]
        client = self.get_client()
        try:
            mail_server_obj = client.model('ir.mail_server')
            return mail_server_obj.load(imp_fields, rows)

        except Exception, e:
            raise except_orm(
                _("Unable to Upload SMTP Config."),
                _('Error: %s') % e
                )

    @api.one
    def config_backups(self):
        self.server_id.get_env()
        client = self.get_client()
        modules = ['database_tools']
        for module in modules:
            if client.modules(name=module, installed=True) is None:
                raise Warning(
                    _("You can not configure backups if module '%s' is not installed in the database") % (module))

        # Configure backups
        self_db_id = client.model('ir.model.data').xmlid_to_res_id(
            'database_tools.db_self_database')
        if self.backups_enable:
            vals = {
                'backups_path': os.path.join(
                    self.instance_id.backups_path, self.name),
                'daily_backup': self.daily_backup,
                'weekly_backup': self.weekly_backup,
                'monthly_backup': self.monthly_backup,
            }
            client.model('db.database').write([self_db_id], vals)
        client.model('db.database').backups_state(
            self.name, self.backups_enable)

    @api.one
    def config_catchall(self):
        self.server_id.get_env()
        client = self.get_client()

        modules = ['auth_server_admin_passwd_passkey', 'mail']
        for module in modules:
            if client.modules(name=module, installed=True) is None:
                raise Warning(
                    _("You can not configure catchall if module '%s' is not installed in the database") % (module))
        if not self.local_alias:
            raise Warning(
                _("You can not configure catchall if Local Alias is not set. Probably this is because Mailgate File was not found"))
        if not exists(self.mailgate_path, use_sudo=True):
            raise Warning(_("Mailgate file was not found on mailgate path '%s' base path found for mail module") % (
                self.mailgate_path))
        # Configure domain_alias on databas
        client.model('ir.config_parameter').set_param(
            "mail.catchall.domain", self.domain_alias or '')

        # clean and append virtual_alias
        if exists(self.server_id.virtual_alias_path, use_sudo=True):
            sed(
                self.server_id.virtual_alias_path,
                '@%s.*' % self.domain_alias, '', use_sudo=True, backup='.bak')
        append(
            self.server_id.virtual_alias_path,
            self.virtual_alias, use_sudo=True, partial=True)

        # clean and append virtual_alias
        if exists(self.server_id.local_alias_path, use_sudo=True):
            sed(
                self.server_id.local_alias_path,
                '%s.*' % self.domain_alias, '', use_sudo=True, backup='.bak')
        append(
            self.server_id.local_alias_path,
            self.local_alias, use_sudo=True)
        sudo('postmap /etc/postfix/virtual_aliases')
        sudo('newaliases')
        sudo('/etc/init.d/postfix restart')

# WORKFLOW
    @api.multi
    def action_wfk_set_draft(self):
        self.write({'state': 'draft'})
        self.delete_workflow()
        self.create_workflow()
        return True