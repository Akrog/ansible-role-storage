# Copyright (c) 2018, Red Hat, Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.


from __future__ import (absolute_import, division, print_function)
import importlib
import json
import os
import sqlite3

import six

import ansible
from ansible.plugins import action
try:
    from ansible.utils import sentinel
except ImportError:
    sentinel = None


DEFAULT_PROVIDER = 'cinderlib'

BLOCK = 1
FILESYSTEM = 2
STORAGE_DATA = 'storage_data'
STORAGE_ATTRIBUTES = 'storage_attributes'
PROVIDER_CONFIG = 'provider_config'
BACKEND_CONFIG = 'backend_config'
CONSUMER_CONFIG = 'consumer_config'


if tuple(map(int, (ansible.__version__.split(".")))) < (2, 7, 0):
    KWARGS_TEMPLATE = {'bare_deprecated': False}
else:
    KWARGS_TEMPLATE = {}


class MissingException(Exception):
    def __init__(self, var):
        msg = 'Missing parameter %s' % var
        super(MissingException, self).__init__(msg)


class NonUnique(Exception):
    def __init__(self, var):
        msg = 'There is not enough info to uniquely identify resource %s' % var
        super(NonUnique, self).__init__(msg)


class NotFound(Exception):
    def __init__(self, var):
        msg = 'Resource %s not found' % var
        super(NotFound, self).__init__(msg)


class BackendObj(object):
    __slots__ = ('id', 'name', 'provider', 'data', 'host', 'attributes',
                 'ctxt')
    FIELDS = __slots__

    def __init__(self, decryptor, values):
        for f, v in zip(self.FIELDS, values):
            setattr(self, f, v)
        # We could lazy load these
        self.attributes = json.loads(self.attributes)
        self.data = decryptor(self.data)

        self.ctxt = decryptor(self.ctxt)
        # Reconstruct sets
        sets = self.ctxt.pop('___sets')
        for key in sets:
            self.ctxt['_attributes'][key] = set(self.ctxt['_attributes'][key])
        sets = self.ctxt.pop('___sets_defaults', tuple())
        for key in sets:
            self.ctxt['_attr_defaults'][key] = set(
                self.ctxt['_attr_defaults'][key])
        # Reconstruct sentinels
        sentinels = self.ctxt.pop('___sentinels')
        for key in sentinels:
            self.ctxt['_attributes'][key] = sentinel.Sentinel

        if '_become_plugin' in self.ctxt:
            become_type, become_vars = self.ctxt['_become_plugin']
            path = become_vars['_original_path'].split(os.path.sep)
            # Remove the .py extension
            path[-1] = path[-1].rsplit('.', 1)[0]
            # Convert to namespace
            namespace = '.'.join(path[path.index('ansible'):])
            # Import and set variables
            module = importlib.import_module(namespace)
            plugin = getattr(module, become_type)()
            vars(plugin).clear()
            vars(plugin).update(become_vars)
            self.ctxt['_become_plugin'] = plugin


class DB(object):
    BACKEND_FIELDS_STR = ', '.join(BackendObj.FIELDS[1:])

    def __init__(self, templar, task_info):
        self.task_info = task_info

        inv = templar.template('inventory_file', convert_bare=True,
                               fail_on_undefined=True, **KWARGS_TEMPLATE)
        inv_path, inv_name = os.path.split(inv)

        self.db = sqlite3.connect(self.task_info['db_name'])
        self.cursor = self.db.cursor()

    def delete_backend(self, backend_id):
        self._delete(id=backend_id)
        self.db.commit()

    def providers(self):
        result = self._query('provider', 'SELECT DISTINCT')
        return [p[0] for p in result if p[0]]

    @staticmethod
    def _build_filters(filters):
        filters = {k: v for k, v in filters.items() if v is not None}
        if not filters:
            return ''
        return ' WHERE ' + ' and '.join('%s=:%s' % (f, f)
                                        for f, v in filters.items() if v)

    def _delete(self, **filters):
        filters_q = self._build_filters(filters)
        query = 'DELETE FROM backends%s' % filters_q
        self.cursor.execute(query, filters)

    def _query(self, fields=None, action='SELECT', **filters):
        if not fields or fields == '*':
            fields = BackendObj.FIELDS

        if isinstance(fields, six.string_types):
            fields = [fields]

        str_fields = ', '.join(fields)

        filters_q = self._build_filters(filters)
        query = '%s %s FROM backends%s' % (action, str_fields, filters_q)
        self.cursor.execute(query, filters)
        results = [BackendObj(self._decrypt, res)
                   for res in self.cursor.fetchall()]
        return results

    def backends(self, provider=None):
        backends = self._query('*', provider=provider)
        return backends

    def backend(self, backend=None, provider=None):
        backends = self._query('*', name=backend, provider=provider)
        if len(backends) == 0:
            raise NotFound({'backend': backend, 'provider': provider})
        if len(backends) > 1:
            raise NonUnique({'backend': backend, 'provider': provider})
        res = backends[0]
        return res

    def create_backend(self, name, provider, data, host, storage_attributes,
                       ctxt):
        data = self._encrypt(data)
        attributes = json.dumps(storage_attributes)
        ctxt = self._encrypt(ctxt)

        args = (name, provider, data, host, attributes, ctxt)

        self.cursor.execute('INSERT INTO backends (%s) VALUES (?, ?, ?, ?, '
                            '?, ?)' % self.BACKEND_FIELDS_STR, args)
        self.db.commit()

    def save_consumer(self, provider, consumer_config, consumer_module):
        config = json.dumps(consumer_config)
        self.cursor.execute('REPLACE INTO providers (name, consumer_data, '
                            'consumer_module) VALUES (?, ?, ?)',
                            (provider, config, consumer_module))
        self.db.commit()

    def get_consumer(self, provider):
        self.cursor.execute('SELECT consumer_data, consumer_module '
                            'FROM providers WHERE name=?', (provider,))
        res = self.cursor.fetchone()
        if not res:
            raise NotFound({'provider': provider})
        return json.loads(res[0]), res[1]

    def _decrypt(self, data):
        # TODO: Decrypt data using self.task_info['secret']
        try:
            return json.loads(data)
        except Exception:
            return data

    def _encrypt(self, data):
        if isinstance(data, dict):
            data = json.dumps(data)

        # TODO: Encrypt data using self.task_info['secret']
        return data


class Resource(object):

    @staticmethod
    def factory(action_module, task, connection, play_context, loader, templar,
                shared_loader_obj):
        args = action_module._task.args
        if 'resource' not in args:
            raise MissingException('resource')

        resource = action_module._task.args['resource']
        if not isinstance(resource, six.string_types):
            raise TypeError('Invalid "resource" type %s' % type(resource))

        cls = globals().get(resource.capitalize())
        if not cls or not issubclass(cls, Resource):
            raise ValueError('Invalid "resource" value %s' % resource)

        return cls(action_module, task, connection, play_context, loader,
                   templar, shared_loader_obj)

    def __init__(self, action_module, task, connection, play_context, loader,
                 templar, shared_loader_obj):
        self._templar = templar
        self.action_module = action_module
        task_info = self._get_var('storage_task_info')
        self.db = DB(templar, task_info)
        self._backend = None
        self._play_context = play_context

    @property
    def context(self):
        ctxt = self.backend().ctxt.copy()
        del ctxt['___fqdn']
        del ctxt['___machine_id']
        return ctxt

    def _get_current_context(self, current=None):
        # Make host context JSON compatible
        ctxt = vars(self._play_context).copy()
        sets = []
        sentinels = []
        attributes = ctxt['_attributes']
        for key, val in attributes.items():
            if isinstance(val, set):
                sets.append(key)
                attributes[key] = list(val)

            elif sentinel and val is sentinel.Sentinel:
                sentinels.append(key)
                del attributes[key]
        ctxt['___sets'] = sets
        ctxt['___sentinels'] = sentinels

        sets2 = []
        if '_attr_defaults' in ctxt:
            defaults = ctxt['_attr_defaults']
            for key, val in defaults.items():
                if isinstance(val, set):
                    sets2.append(key)
                    defaults[key] = list(val)
            ctxt['___sets_defaults'] = sets2

        ctxt['___fqdn'] = self._get_var('ansible_fqdn')
        ctxt['___machine_id'] = self._get_var('ansible_machine_id')

        if '_become_plugin' in ctxt:
            ctxt['_become_plugin'] = (type(ctxt['_become_plugin']).__name__,
                                      vars(ctxt['_become_plugin']))
            ctxt['_connection_opts'] = self.action_module._connection._options

        return ctxt

    def _get_controller_data(self):
        try:
            return self.backend().data
        except NotFound:
            return {}

    def runner(self, module_args=None, ctrl=True, **kwargs):
        if module_args is None:
            module_args = {}
        if ctrl:
            module_data = self._get_controller_data()
            module_name = self.provider_name + '_storage_controller'
            if self._backend:
                module_args.setdefault('backend', self._backend.name)
                module_args.setdefault('provider', self._backend.provider)
        else:
            module_data, module_name = self.db.get_consumer(self.provider_name)
        module_args[STORAGE_DATA] = module_data

        # If this is a controller operation called on consumer pass
        # controller context
        if (ctrl and module_args.get('resource') != 'backend' and
                self.backend().host != self._get_var('ansible_machine_id')):
            kwargs['context'] = self.context

        return self.action_module.runner(module_name, module_args, **kwargs)

    @property
    def task(self):
        return self.action_module._task

    def _select_backend(self):
        if self._backend:
            return

        provider = self.task.args.get('provider')
        backend = self.task.args.get('backend')

        backends = self.db._query('*', provider=provider, name=backend)

        if not backends:
            raise NotFound({'backend': backend, 'provider': provider})

        if len(backends) == 1:
            self._backend = backends[0]
            return

        for backend in backends:
            if backend.provider == DEFAULT_PROVIDER:
                self._backend = backend
                return
        raise NonUnique({'backend': backend, 'provider': provider})

    def backend(self):
        self._select_backend()
        return self._backend

    @property
    def provider_name(self):
        provider = self.task.args.get('provider')
        if provider:
            return provider

        self._select_backend()
        return self._backend.provider

    def execute(self, task_vars):
        self.task_vars = task_vars
        result = self.run()
        return result or {}

    def _get_var(self, name):
        if hasattr(self, 'task_vars') and name in self.task_vars:
            return self.task_vars[name]

        return self._templar.template(name, convert_bare=True,
                                      fail_on_undefined=True,
                                      **KWARGS_TEMPLATE)

    def _get_brick_info(self):
        args = self.task.args.copy()
        ips = self._get_var('ansible_all_ipv4_addresses') or []
        ipv6 = self._get_var('ansible_all_ipv6_addresses') or []
        ips.extend(ipv6)
        pass_args = {
            'resource': 'node',
            'ips': ips,
            'multipath': args.get('multipath', True),
            'enforce_multipath': args.get('enforce_multipath', False)
        }
        return self.runner(pass_args, ctrl=False)

    def default_state_run(self, args):
        return self.runner(args)

    def run(self):
        state_runner = getattr(self, self.task.args.get('state'),
                               self.default_state_run)
        return state_runner(self.task.args)


class Node(Resource):
    def run(self):
        return self._get_brick_info()


class Backend(Resource):
    # stats is handled by Resource.default_state_run
    def stats(self, args):
        return self.default_state_run(args)

    def present(self, args):
        consumer_config = self.task.args.pop('consumer_config', {})

        result = self.runner(self.task.args)
        if result.get('failed'):
            return result

        storage_data = result.pop(STORAGE_DATA, '')
        attributes = result.pop(STORAGE_ATTRIBUTES, {})
        ctxt = self._get_current_context()
        host = self.task_vars.get('ansible_machine_id')
        self.db.create_backend(self.task.args['backend'],
                               self.provider_name,
                               storage_data,
                               host,
                               attributes,
                               ctxt)

        # By default we assume controller module returns data conforming to the
        # cinderlib consumer module that can handle many different connections.
        consumer = attributes.get('consumer', 'cinderlib_storage_consumer')
        self.db.save_consumer(self.provider_name,
                              {CONSUMER_CONFIG: consumer_config},
                              consumer)

    def absent(self, args):
        result = self.runner(self.task.args)
        if result.get('failed'):
            return result
        self.db.delete_backend(self.backend().id)


class Volume(Resource):
    # present and absent states handled by Resource.default_state_run
    def connected(self, args):
        pass_args = args.copy()
        # The connection info must be the connection module name + _info
        conn_info_key = self.db.get_consumer(self.provider_name)[1] + '_info'
        conn_info = self.task_vars.get(conn_info_key)
        if conn_info:
            pass_args.update(conn_info)
        else:
            result = self._get_brick_info()

            if result.get('failed', False):
                return result

            pass_args.update(result[STORAGE_DATA])

        pass_args.setdefault('provider', self.provider_name)
        pass_args['attached_host'] = self._get_var('ansible_fqdn')

        result = self.runner(pass_args)

        if result.get('failed', False):
            return result

        pass_args = args.copy()
        pass_args.setdefault('provider', self.provider_name)
        pass_args.update(result[STORAGE_DATA])

        result = self.runner(pass_args, ctrl=False)
        return result

    def disconnected(self, args):
        args = args.copy()
        args.setdefault('provider', self.provider_name)
        result = self.runner(args, ctrl=False)
        if result.get('failed', False):
            return result

        pass_args = args.copy()
        pass_args['attached_host'] = self._get_var('ansible_fqdn')
        result = self.runner(pass_args)
        return result

    def extended(self, args):
        # Make the controller request the extend on the backend
        result = self.runner(args)
        if result.get('failed', False):
            return result

        # Make the node notice if it has changed and is attached
        if result['attached_host']:
            pass_args = args.copy()
            # We cannot pass the size or the node won't find the attachment
            pass_args.pop('size')
            pass_args.pop('old_size', None)
            pass_args['provider'] = self.provider_name
            # pass_args.update(result[STORAGE_DATA])
            result = self.runner(pass_args, ctrl=False)
            if result.get('failed', False):
                return result
        return result

    def run(self):
        original_args = self.task.args.copy()
        # Automatically set the host parameter
        self.task.args.setdefault('host', self._get_var('ansible_fqdn'))
        try:
            return super(Volume, self).run()
        finally:
            self.task.args = original_args


class ActionModule(action.ActionBase):
    def __init__(self, task, connection, play_context, loader, templar,
                 shared_loader_obj):
        # Expand kwargs parameter
        kwargs = task.args.pop('kwargs', None)
        if kwargs:
            task.args.update(**kwargs)

        super(ActionModule, self).__init__(task, connection, play_context,
                                           loader, templar, shared_loader_obj)
        self.resource = Resource.factory(self, task, connection, play_context,
                                         loader, templar, shared_loader_obj)

    def runner(self, module_name, module_args, context=None, **kwargs):
        task_vars = kwargs.pop('task_vars', self.task_vars)
        if context:
            original_ctxt = self._play_context.__dict__
            original_connection = self._connection

            self._play_context.__dict__ = context
            conn_type = self._play_context.connection
            self._connection = self._shared_loader_obj.connection_loader.get(
                conn_type, self._play_context, self._connection._new_stdin)
            if '_connection_opts' in context:
                self._connection._options.update(context['_connection_opts'])
                self._connection.become = context['_become_plugin']
        try:
            result = self._execute_module(module_name=module_name,
                                          module_args=module_args,
                                          task_vars=task_vars)
        finally:
            if context:
                self._play_context.__dict__ = original_ctxt
                self._connection = original_connection
        return result

    def run(self, tmp=None, task_vars=None):
        self.task_vars = task_vars
        self._supports_check_mode = False
        self._supports_async = True

        result = self.resource.execute(task_vars)

        # hack to keep --verbose from showing all the setup module result moved
        # from setup module as now we filter out all _ansible_ from result
        if self._task.action == 'setup':
            result['_ansible_verbose_override'] = True

        return result
