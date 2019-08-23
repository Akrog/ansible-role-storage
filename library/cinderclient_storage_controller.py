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

import os
import time
import uuid

# from ansible.module_utils.
# from ansible.module_utils import basic

from cinderclient import client as cinder
from cinderclient import exceptions
from keystoneauth1 import loading

from ansible.module_utils.storage import base
from ansible.module_utils.storage import common


HOME = os.path.expanduser("~")

REFRESH_TIME = 1


class Resource(base.Resource):
    def __init__(self, *args, **kwargs):
        super(Resource, self).__init__(*args, **kwargs)
        self.backend = self._setup(self.storage_data)

    def _setup(self, storage_data):
        if not storage_data:
            return None

        params = storage_data[common.BACKEND_CONFIG].copy()
        params.pop('provider')
        self.volume_backend_name = params.pop('volume_backend_name', None)
        self.volume_type = params.pop('volume_type', None)

        loader = loading.base.get_plugin_loader(params.pop('auth_system'))
        auth_cfg = {k: params.pop(k)
                    for k in ('auth_url', 'username', 'password',
                              'project_name', 'user_domain_id',
                              'project_domain_id')}
        plugin = loader.load_from_options(**auth_cfg)
        auth_session = loading.session.Session().load_from_options(auth=plugin)
        params.update(auth_plugin=plugin, session=auth_session)
        client = cinder.Client(**params)
        return client


@Resource.register
class Backend(Resource, base.Backend):
    # backend is equivalent to volume type
    BACKEND_CONFIG_SPECS = {
        'auth_system': {'type': 'str', 'default': 'password'},
        'password': {'type': 'str'},
        'auth_url': {'type': 'str'},
        'project_name': {'type': 'str'},
        'user_domain_id': {'type': 'str', 'default': 'default'},
        'project_domain_id': {'type': 'str', 'default': 'default'},
        'region_name': {'type': 'str', 'required': True},
        'username': {'type': 'str', 'required': True},
        'version': {'type': 'str', 'default': '3.27'},
        'volume_type': {'type': 'str'},
    }

    @Resource.state
    def present(self, params):
        if not params.get('backend'):
            return {'failed': True,
                    'msg': 'missing required argument: backend'}

        self.backend = self._setup(params)

        if self.volume_type:
            vol_type = self.backend.volume_types.find(name=self.volume_type)
        else:
            vol_type = self.backend.volume_types.default()

        backend_name = vol_type.extra_specs.get('volume_backend_name')
        params[common.BACKEND_CONFIG]['volume_backend_name'] = backend_name
        params[common.BACKEND_CONFIG]['volume_type'] = vol_type.name

        result = {
            common.STORAGE_DATA: params,
            common.STORAGE_ATTRIBUTES: {
                'type': common.BLOCK,
                'consumer': 'cinderlib_storage_consumer'
            }
        }
        return result

    @Resource.state
    def stats(self, params):
        stats = self.backend.pools.list(detailed=True)

        if self.volume_backend_name:
            stats = [p for p in stats
                     if p.volume_backend_name == self.volume_backend_name]

        if not stats:
            stats = {}
        elif len(stats) == 1:
            stats = stats[0].to_dict()['capabilities']

        return {'changed': False, 'result': stats}

    @Resource.state
    def absent(self, params):
        return {'changed': True}


@Resource.register
class Volume(Resource, base.Volume):
    METADATA_FIELDS = ('id', 'host', 'backend')

    @classmethod
    def _to_json(cls, vol):
        res = {'id': vol.id, 'name': vol.name, 'size': vol.size, 'type': 'volume'}
        for key, value in vol.metadata.items():
            if key in cls.METADATA_FIELDS:
                res[key] = value
        return res

    def _matches(self, vol, params):
        return ((params.get('size') or vol.size) == vol.size and
                self.volume_type == vol.volume_type)

    @staticmethod
    def _build_cinderclient_params(params):
        metadata = {'backend': params['backend']}
        cparams = {'metadata': metadata}
        if params.get('name'):
            cparams['name'] = params['name']
        if params.get('id'):
            metadata['id'] = params['id']
        if params.get('host'):
            metadata['host'] = params['host']
        return cparams

    def _get_volume(self, params, fail_not_found=False):
        clean_params = {k: v for k, v in params.items() if v is not None}
        search_opts = self._build_cinderclient_params(clean_params)
        vs = self.backend.volumes.list(detailed=True, search_opts=search_opts)

        # We cannot filter Cinder's list by size or type, so we do it here
        filtered_vs = [v for v in vs if self._matches(v, clean_params)]

        if not filtered_vs:
            if fail_not_found:
                self.fail('Volume could not be found')
            return None

        if len(filtered_vs) > 1:
            self.fail('Multiple volumes found')

        return filtered_vs[0]

    def _wait(self, vol, states, delete_on_error=False):
        while True:
            if vol.status in states:
                return
            if 'error' in vol.status:
                if delete_on_error:
                    vol.force_delete()
                self.fail('Volume is on error')
            time.sleep(REFRESH_TIME)
            vol = self.backend.volumes.get(vol.id)

    @Resource.state
    def present(self, params):
        vol = self._get_volume(params)
        result = {'changed': not bool(vol)}
        if not vol:
            cparams = self._build_cinderclient_params(params)
            vol = self.backend.volumes.create(size=params['size'],
                                              volume_type=self.volume_type,
                                              **cparams)

            self._wait(vol, ('available',), delete_on_error=True)

        result.update(self._to_json(vol))
        return result

    @Resource.state
    def absent(self, params):
        vol = self._get_volume(params)

        if vol:
            vol.delete()
            try:
                self._wait(vol, [])
            except exceptions.NotFound as exc:
                pass

        return {'changed': bool(vol)}

    def _get_connection(self, volume, host):
        cs = self.backend.attachments.list(
            detailed=True, search_opts={'volume_id': volume.id,
                                        'instance_uuid': host})

        if cs:
            return cs[0]

        return None

    @Resource.state
    def connected(self, params):
        vol = self._get_volume(params, fail_not_found=True)
        host_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS,
                                   params['attached_host']))
        connection = self._get_connection(vol, host_uuid)
        result = {'changed': not bool(connection)}
        if connection:
            connection = connection.connection_info
        else:
            connection = self.backend.attachments.create(
                vol.id, params['connector_dict'], host_uuid)
            connection = connection['connection_info']

        # Returning the volume information allows consumer to disconnect even
        # if we pass different data on the task.
        storage_data = self._to_json(vol)
        storage_data.pop('type')
        storage_data[common.CONNECTION_INFO] = {
            'conn': {'data': connection,
                     'driver_volume_type': connection['driver_volume_type']},
            'connector': params['connector_dict'],
        }
        result[common.STORAGE_DATA] = storage_data
        return result

    @Resource.state
    def disconnected(self, params):
        vol = self._get_volume(params, fail_not_found=True)
        host_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS,
                                   params['attached_host']))
        connection = self._get_connection(vol, host_uuid)

        if connection:
            self.backend.attachments.delete(connection.id)

        return {'changed': bool(connection)}

    @Resource.state
    def extended(self, params):
        params = params.copy()
        new_size = params.pop('size')
        old_size = params.pop('old_size')
        if old_size:
            params['size'] = old_size
        vol = self._get_volume(params)
        # The volume may have already been extended
        if not vol and 'size' in params:
            params['size'] = new_size
            vol = self._get_volume(params, fail_not_found=True)

        if vol.size > new_size:
            raise Exception('Volumes cannot be shrinked')

        result = {'changed': False, 'new_size': new_size}
        if new_size != vol.size:
            result['changed'] = True
            self.backend.volumes.extend(vol, new_size)

        # TODO: Support multiattach, return list and iterate in action plugin
        conn = self._get_connection(vol, params['host'])
        if conn:
            result['attached_host'] = params['host']

        return result


def main():
    # This instantiates a resource and checks provided parameters
    resource = Resource.resource_factory()
    result = resource.process()
    # If successful execution output results in JSON format.
    resource.exit(**result)


if __name__ == '__main__':
    main()
