#!/usr/bin/python

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
#

import errno
import os

# from ansible.module_utils.
# from ansible.module_utils import basic

from ansible.module_utils.storage import base
from ansible.module_utils.storage import common

import cinderlib

HOME = os.path.expanduser("~")


class Resource(base.Resource):
    def __init__(self, *args, **kwargs):
        # If at some point we have a base class that overwrites __init__ we can
        # use this to call it.
        # bases = [b for b in self.__class__.__bases__
        #          if b is not Resource and issubclass(b,base.Resource)]
        # if bases:
        #     for base in bases:
        #         base.__init__(self, *args, **kwargs)
        # else:
        #     super(Resource, self).__init__(*args, **kwargs)
        super(Resource, self).__init__(*args, **kwargs)
        self.backend = self._setup(self.storage_data)

    def _setup(self, storage_data):
        if not storage_data:
            return None

        cinderlib.setup(**storage_data[common.PROVIDER_CONFIG])
        backend = cinderlib.Backend(**storage_data[common.BACKEND_CONFIG])
        return backend

    def execute(self, params):
        # Check that the backend matches our own
        if (self.backend and params.get('backend') and
                self.backend.id != params['backend']):
            self.fail("Backend %s can't handle requests for %s" %
                      (self.backend.id, params['backend']))
        return super(Resource, self).execute(params)


@Resource.register
class Backend(Resource, base.Backend):
    DEFAULT_PERSISTENCE = {
        'storage': 'db',
        'connection': 'sqlite:///' + os.path.join(HOME, 'mydb.sqlite'),
    }
    DEFAULT_LOCKS_PATH = os.path.join(HOME, 'cinderlib_locks')
    DEFAULT_DB_FILE = 'storage_cinderlib_consumer.sqlite'
    PROVIDER_CONFIG_SPECS = {
        'disable_logs': {'type': 'bool', 'default': True},
        'use_stderr': {'type': 'bool', 'default': False},
        'debug': {'type': 'bool', 'default': False},
        'verbose': {'type': 'bool', 'default': False},
        'db_file': {'type': 'path', 'default': DEFAULT_DB_FILE},
        'locks_path': {'type': 'path', 'default': DEFAULT_LOCKS_PATH},
        'persistence_config': {'type': 'dict',
                               'default': DEFAULT_PERSISTENCE},
        'disable_sudo': {'type': 'bool', 'default': False},
    }
    BACKEND_CONFIG_SPECS = {
        'volume_driver': {'type': 'str'},
    }

    @Resource.state
    def present(self, params):
        if not params.get('backend'):
            return {'failed': True,
                    'msg': 'missing required argument: backend'}

        backend_config = params[common.BACKEND_CONFIG].copy()
        backend_config['volume_backend_name'] = params['backend']

        provider_config = params[common.PROVIDER_CONFIG].copy()

        # Set consumer config
        db_file = provider_config.pop('db_file')
        self.makedirs(provider_config['locks_path'])

        storage_data = {common.PROVIDER_CONFIG: provider_config,
                        common.BACKEND_CONFIG: backend_config}

        self._setup(storage_data)

        result = {
            common.STORAGE_DATA: storage_data,
            common.STORAGE_ATTRIBUTES: {
                'type': common.BLOCK,
                'consumer': 'cinderlib_storage_consumer'
            }
        }
        return result

    @Resource.state
    def stats(self, params):
        stats = self.backend.stats(refresh=True)
        return {'changed': False, 'result': stats}

    @Resource.state
    def absent(self, params):
        return {'changed': True}

    @staticmethod
    def makedirs(path):
        try:
            os.makedirs(path)
        except OSError as exc:
            if exc.errno != errno.EEXIST or not os.path.isdir(path):
                raise


@Resource.register
class Volume(Resource, base.Volume):
    FIELDS_MAP = {'id': 'id', 'name': 'name', 'size': 'size', 'host': 'host',
                  'cluster_name': 'cluster_name'}

    @classmethod
    def _to_json(cls, vol):
        res = {k: getattr(vol, v) for k, v in cls.FIELDS_MAP.items()}
        res['type'] = 'volume'
        # Since cluster name and backend name are the same...
        res['backend'] = vol.cluster_name.split('@')[0]
        return res

    def _matches(self, vol, params):
        for k, v in self.FIELDS_MAP.items():
            if params.get(k) and getattr(vol, v) != params[k]:
                return False
        return True

    def _get_volume(self, params, fail_not_found=False):
        vs = self.backend.persistence.get_volumes(volume_id=params['id'],
                                                  volume_name=params['name'],
                                                  backend_name=self.backend.id)
        filtered_vs = [v for v in vs if self._matches(v, params)]

        if not filtered_vs:
            if fail_not_found:
                self.fail('Volume could not be found with params %s' % params)
            return None

        if len(filtered_vs) > 1:
            self.fail('Multiple volumes found')

        return filtered_vs[0]

    def _prepare_params(self, params):
        new_params = params.copy()
        pool_name = self.backend.pool_names[0]
        new_params['host'] = '%s@%s#%s' % (params['host'],
                                           self.backend.id,
                                           pool_name)
        new_params['cluster_name'] = '%s@%s#%s' % (self.backend.id,
                                                   self.backend.id,
                                                   pool_name)
        return new_params

    @Resource.state
    def present(self, params):
        # TODO: Add support for pools
        params = self._prepare_params(params)
        vol = self._get_volume(params)
        result = {'changed': not bool(vol)}
        if not vol:
            vol = self.backend.create_volume(
                size=params['size'], name=params['name'], id=params['id'],
                host=params['host'], cluster_name=params['cluster_name'])
        result.update(self._to_json(vol))
        return result

    @Resource.state
    def absent(self, params):
        params = self._prepare_params(params)
        vol = self._get_volume(params)
        if vol:
            vol.delete()

        return {'changed': bool(vol)}

    def _get_connection(self, volume, host):
        for c in volume.connections:
            if c.attached_host == host:
                return c
        return None

    @Resource.state
    def connected(self, params):
        params = self._prepare_params(params)
        vol = self._get_volume(params, fail_not_found=True)
        connection = self._get_connection(vol, params['attached_host'])
        result = {'changed': not bool(connection)}
        if not connection:
            connection = vol.connect(params['connector_dict'],
                                     attached_host=params['attached_host'])

        # Returning the volume information allows consumer to disconnect even
        # if we pass different data on the task.
        storage_data = self._to_json(vol)
        storage_data.pop('type')
        storage_data[common.CONNECTION_INFO] = connection.connection_info
        result[common.STORAGE_DATA] = storage_data
        return result

    @Resource.state
    def disconnected(self, params):
        params = self._prepare_params(params)
        vol = self._get_volume(params, fail_not_found=True)
        connection = self._get_connection(vol, params['attached_host'])
        if connection:
            connection.disconnect()

        return {'changed': bool(connection)}


def main():
    # This instantiates a resource and checks provided parameters
    resource = Resource.resource_factory()
    result = resource.process()
    # If successful execution output results in JSON format.
    resource.exit(**result)


if __name__ == '__main__':
    main()
