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

import functools
import json
import os
import sqlite3

# from ansible.module_utils.
from ansible.module_utils import basic
from ansible.module_utils import common

import six

from os_brick import exception
from os_brick.initiator import connector
from os_brick.initiator import connectors
from os_brick.privileged import rootwrap
from oslo_concurrency import processutils as putils
from oslo_utils import fileutils


class RBDConnector(connectors.rbd.RBDConnector):
    """"Connector class to attach/detach RBD volumes locally.

    OS-Brick's implementation covers only 2 cases:

    - Local attachment on controller node.
    - Returning a file object on non controller nodes.

    We need a third one, local attachment on non controller node.
    """
    def connect_volume(self, connection_properties):
        # NOTE(e0ne): sanity check if ceph-common is installed.
        try:
            self._execute('which', 'rbd')
        except putils.ProcessExecutionError:
            raise exception.BrickException('ceph-common package not installed')

        # Extract connection parameters and generate config file
        try:
            user = connection_properties['auth_username']
            pool, volume = connection_properties['name'].split('/')
            cluster_name = connection_properties.get('cluster_name')
            monitor_ips = connection_properties.get('hosts')
            monitor_ports = connection_properties.get('ports')
            keyring = connection_properties.get('keyring')
        except IndexError:
            raise exception.BrickException('Malformed connection properties')

        conf = self._create_ceph_conf(monitor_ips, monitor_ports,
                                      str(cluster_name), user,
                                      keyring)

        # Map RBD volume if it's not already mapped
        rbd_dev_path = self.get_rbd_device_name(pool, volume)
        if (not os.path.islink(rbd_dev_path) or
                not os.path.exists(os.path.realpath(rbd_dev_path))):
            cmd = ['rbd', 'map', volume, '--pool', pool, '--conf', conf]
            cmd += self._get_rbd_args(connection_properties)
            self._execute(*cmd, root_helper=self._root_helper,
                          run_as_root=True)

        return {'path': os.path.realpath(rbd_dev_path),
                'conf': conf,
                'type': 'block'}

    def check_valid_device(self, path, run_as_root=True):
        """Verify an existing RBD handle is connected and valid."""
        try:
            self._execute('dd', 'if=' + path, 'of=/dev/null', 'bs=4096',
                          'count=1', root_helper=self._root_helper,
                          run_as_root=True)
        except putils.ProcessExecutionError:
            return False
        return True

    def disconnect_volume(self, connection_properties, device_info,
                          force=False, ignore_errors=False):

        pool, volume = connection_properties['name'].split('/')
        conf_file = device_info['conf']
        dev_name = self.get_rbd_device_name(pool, volume)
        cmd = ['rbd', 'unmap', dev_name, '--conf', conf_file]
        cmd += self._get_rbd_args(connection_properties)
        self._execute(*cmd, root_helper=self._root_helper,
                      run_as_root=True)
        fileutils.delete_if_exists(conf_file)


def attach_volume(db, module):
    conn = _get_data(db, module)
    if conn:
        path = conn['device'].pop('path')
        return {'changed': False,
                'path': path,
                'type': common.BLOCK,
                'additional_data': conn['device']}

    params = module.params
    conn_info = params[common.CONNECTION_INFO]['conn']
    connector_dict = params[common.CONNECTION_INFO]['connector']
    protocol = conn_info['driver_volume_type']

    # NOTE(geguileo): afaik only remotefs uses connection info
    conn = connector.InitiatorConnector.factory(
        protocol, 'sudo', user_multipath=connector_dict['multipath'],
        device_scan_attempts=params.get('scan_attempts', 3),
        conn=connector_dict)
    device = conn.connect_volume(conn_info['data'])
    try:
        unavailable = not conn.check_valid_device(device.get('path'))
    except Exception:
        unavailable = True

    if unavailable:
        module.fail_json(msg='Unable to access backend storage once attached.')

    additional_data = device.copy()
    additional_data.pop('path')

    data = {'device': device, common.CONNECTION_INFO: conn_info,
            'connector': connector_dict}

    _save_attachment(db, params, data)

    return {'path': device['path'],
            'type': common.BLOCK,
            'additional_data': additional_data,
            'changed': True}


def detach_volume(db, module):
    data = _get_data(db, module)
    if not data:
        return {'changed': False}

    connector_dict = data['connector']
    conn_info = data[common.CONNECTION_INFO]
    protocol = conn_info['driver_volume_type']
    device = data['device']
    # NOTE(geguileo): afaik only remotefs uses connection info
    conn = connector.InitiatorConnector.factory(
        protocol, 'sudo', user_multipath=connector_dict['multipath'],
        device_scan_attempts=3, conn=connector_dict)
    conn.disconnect_volume(conn_info['data'], device, force=False,
                           ignore_errors=False)
    _delete_attachment(db, module)
    return {'changed': True}


def _validate_volume(module):
    specs = module.argument_spec.copy()
    specs.update(state={'choices': ('connected', 'disconnected'),
                        'required': True},
                 provider={'type': 'str'},
                 backend={'type': 'str'},
                 name={'type': 'str'},
                 id={'type': 'str'},
                 size={'type': 'int'},
                 host={'type': 'str', 'default': ''},
                 cluster_name={'type': 'str', 'default': ''},
                 attached_host={'type': 'str', 'default': ''})

    if module.params.get('state') == 'connected':
        specs[common.CONNECTION_INFO] = {'type': 'dict', 'required': True}

    new_module = basic.AnsibleModule(specs, check_invalid_arguments=True)
    return new_module


DB_FIELDS = ('id', 'name', 'provider', 'backend', 'host', 'size', 'data')


def _setup_db(params):
    config = params[common.STORAGE_DATA][common.CONSUMER_CONFIG]
    db = sqlite3.connect(config['db_file'])
    cursor = db.cursor()
    fields = ' TEXT,'.join(DB_FIELDS) + ' TEXT'
    cursor.execute('CREATE TABLE IF NOT EXISTS attachments (' + fields + ')')
    db.commit()
    cursor.close()
    return db


def _save_attachment(db, params, data):
    data = json.dumps(data)
    values = tuple(six.text_type(params[k]) if params[k] else params[k]
                   for k in DB_FIELDS[:-1]) + (data,)
    fields = ','.join('?' * len(DB_FIELDS))
    cursor = db.cursor()
    cursor.execute('INSERT INTO attachments VALUES (%s)' % fields, values)
    db.commit()
    cursor.close()


def __generate_where(params):
    def _partial(field):
        if field == 'host':
            res = '%s LIKE :%s%@%'
        else:
            res = '%s=:%s'
        return res % (field, field)

    filters = {k: params[k] for k in ('id', 'name', 'provider', 'backend',
                                      'name', 'size')
               if params.get(k)}

    if filters:
        query_str = ' WHERE ' + ' and '.join(_partial(f) for f in filters)
    else:
        query_str = ''
    if filters.get('host'):
        filters['host'] = filters['host'] + '@%'

    return query_str, filters


def _get_data(db, module, fail_on_missing=False):
    query_str = 'SELECT data FROM attachments'
    where_str, filters = __generate_where(module.params)
    cursor = db.cursor()
    cursor.execute(query_str + where_str, filters)
    results = [json.loads(res[0]) for res in cursor.fetchall()]
    cursor.close()
    if not results:
        if fail_on_missing:
            module.fail_json('No attachment found')
        return None

    if len(results) > 1:
        module.fail_json('Multiple attachments found')

    return results[0]


def _delete_attachment(db, module):
    query_str = 'DELETE FROM attachments'
    where_str, filters = __generate_where(module.params)
    cursor = db.cursor()
    cursor.execute(query_str + where_str, filters)
    db.commit()
    cursor.close()


def volume(module):
    new_module = _validate_volume(module)
    db = _setup_db(module.params)
    if new_module.params['state'] == 'connected':
        result = attach_volume(db, new_module)
    else:
        result = detach_volume(db, new_module)
    return result


def node(module):
    specs = module.argument_spec
    specs.update(ips={'type': 'list', 'required': True},
                 multipath={'type': 'bool', 'default': True},
                 enforce_multipath={'type': 'bool', 'default': True})
    module = basic.AnsibleModule(module.argument_spec,
                                 check_invalid_arguments=True)

    connector_dict = connector.get_connector_properties(
        root_helper='sudo',
        my_ip=module.params['ips'][0],
        multipath=module.params['multipath'],
        enforce_multipath=module.params['enforce_multipath'])
    return {common.STORAGE_DATA: {common.CONNECTOR_DICT: connector_dict}}


def _set_priv_helper(root_helper):
    # utils.get_root_helper = lambda: root_helper
    # volume_cmd.priv_context.init(root_helper=[root_helper])

    existing_bgcp = connector.get_connector_properties
    existing_bcp = connector.InitiatorConnector.factory

    def my_bgcp(*args, **kwargs):
        if len(args):
            args = list(args)
            args[0] = root_helper
        else:
            kwargs['root_helper'] = root_helper
        kwargs['execute'] = rootwrap.custom_execute
        return existing_bgcp(*args, **kwargs)

    def my_bgc(protocol, *args, **kwargs):
        if len(args):
            # args is a tuple and we cannot do assignments
            args = list(args)
            args[0] = root_helper
        else:
            kwargs['root_helper'] = root_helper
        kwargs['execute'] = rootwrap.custom_execute

        # OS-Brick's implementation for RBD is not good enough for us
        if protocol == 'rbd':
            factory = RBDConnector
        else:
            factory = functools.partial(existing_bcp, protocol)

        return factory(*args, **kwargs)

    connector.get_connector_properties = my_bgcp
    connector.InitiatorConnector.factory = staticmethod(my_bgc)


def main():
    consumer_config = {common.CONSUMER_CONFIG: {'type': 'dict'}}
    module = basic.AnsibleModule(
        argument_spec={
            'resource': {'required': True, 'choices': ('node', 'volume')},
            common.STORAGE_DATA: {'type': 'dict', 'options': consumer_config},
        },
        supports_check_mode=False,
        check_invalid_arguments=False,
    )

    _set_priv_helper('sudo')

    method = globals()[module.params['resource']]
    module.exit_json(**method(module))


if __name__ == '__main__':
    main()
