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
import functools
import json
import os
import sqlite3
import traceback

# from ansible.module_utils.
from ansible.module_utils import basic
from ansible.module_utils.storage import common

import six

from os_brick import exception
from os_brick.initiator import connector
from os_brick.initiator import connectors
from os_brick.privileged import rootwrap
from oslo_concurrency import processutils as putils
from oslo_utils import fileutils
from oslo_utils import strutils


class RBDConnector(connectors.rbd.RBDConnector):
    """"Connector class to attach/detach RBD volumes locally.

    OS-Brick's implementation covers only 2 cases:

    - Local attachment on controller node.
    - Returning a file object on non controller nodes.

    We need a third one, local attachment on non controller node.
    """
    def connect_volume(self, connection_properties):
        # NOTE(e0ne): sanity check if ceph-common is installed.
        self._setup_rbd_class()

        # Extract connection parameters and generate config file
        try:
            user = connection_properties['auth_username']
            pool, volume = connection_properties['name'].split('/')
            cluster_name = connection_properties.get('cluster_name')
            monitor_ips = connection_properties.get('hosts')
            monitor_ports = connection_properties.get('ports')
            keyring = connection_properties.get('keyring')
        except IndexError:
            msg = 'Malformed connection properties'
            raise exception.BrickException(msg)

        conf = self._create_ceph_conf(monitor_ips, monitor_ports,
                                      str(cluster_name), user,
                                      keyring)

        link_name = self.get_rbd_device_name(pool, volume)
        real_path = os.path.realpath(link_name)

        try:
            # Map RBD volume if it's not already mapped
            if not os.path.islink(link_name) or not os.path.exists(real_path):
                cmd = ['rbd', 'map', volume, '--pool', pool, '--conf', conf]
                cmd += self._get_rbd_args(connection_properties)
                stdout, stderr = self._execute(*cmd,
                                               root_helper=self._root_helper,
                                               run_as_root=True)
                real_path = stdout.strip()
                # The host may not have RBD installed, and therefore won't
                # create the symlinks, ensure they exist
                if self.containerized:
                    self._ensure_link(real_path, link_name)
        except Exception as exec_exception:
            try:
                try:
                    self._unmap(real_path, conf, connection_properties)
                finally:
                    fileutils.delete_if_exists(conf)
            except Exception:
                exc = traceback.format_exc()
                print('Exception occurred while cleaning up after connection '
                      'error\n%s', exc)
            finally:
                raise exception.BrickException('Error connecting volume: %s' %
                                               six.text_type(exec_exception))

        return {'path': real_path,
                'conf': conf,
                'type': 'block'}

    def _ensure_link(self, source, link_name):
        self._ensure_dir(os.path.dirname(link_name))
        if self.im_root:
            # If the link exists, remove it in case it's a leftover
            if os.path.exists(link_name):
                os.remove(link_name)
            try:
                os.symlink(source, link_name)
            except OSError as exc:
                # Don't fail if symlink creation fails because it exists.
                # It means that ceph-common has just created it.
                if exc.errno != errno.EEXIST:
                    raise
        else:
            self._execute('ln', '-s', '-f', source, link_name,
                          run_as_root=True)

    def check_valid_device(self, path, run_as_root=True):
        """Verify an existing RBD handle is connected and valid."""
        if self.im_root:
            try:
                with open(path, 'r') as f:
                    f.read(4096)
            except Exception:
                return False
            return True

        try:
            self._execute('dd', 'if=' + path, 'of=/dev/null', 'bs=4096',
                          'count=1', root_helper=self._root_helper,
                          run_as_root=True)
        except putils.ProcessExecutionError:
            return False
        return True

    def _unmap(self, real_dev_path, conf_file, connection_properties):
        if os.path.exists(real_dev_path):
            cmd = ['rbd', 'unmap', real_dev_path, '--conf', conf_file]
            cmd += self._get_rbd_args(connection_properties)
            self._execute(*cmd, root_helper=self._root_helper,
                          run_as_root=True)

    def disconnect_volume(self, connection_properties, device_info,
                          force=False, ignore_errors=False):
        self._setup_rbd_class()
        pool, volume = connection_properties['name'].split('/')
        conf_file = device_info['conf']
        link_name = self.get_rbd_device_name(pool, volume)
        real_dev_path = os.path.realpath(link_name)

        self._unmap(real_dev_path, conf_file, connection_properties)
        if self.containerized:
            unlink_root(link_name)
        fileutils.delete_if_exists(conf_file)

    def _ensure_dir(self, path):
        if self.im_root:
            try:
                os.makedirs(path, 0o755)
            except OSError as exc:
                # Don't fail if directory already exists, as our job is done.
                if exc.errno != errno.EEXIST:
                    raise
        else:
            self._execute('mkdir', '-p', '-m0755', path, run_as_root=True)

    def _setup_class(self):
        try:
            self._execute('which', 'rbd')
        except putils.ProcessExecutionError:
            msg = 'ceph-common package not installed'
            raise exception.BrickException(msg)

        RBDConnector.im_root = os.getuid() == 0
        # Check if we are running containerized
        RBDConnector.containerized = os.stat('/proc').st_dev > 4

        # Don't check again to speed things on following connections
        RBDConnector._setup_rbd_class = lambda *args: None

    _setup_rbd_class = _setup_class


ROOT_HELPER = 'sudo'


def unlink_root(*links, **kwargs):
    no_errors = kwargs.get('no_errors', False)
    raise_at_end = kwargs.get('raise_at_end', False)
    exc = exception.ExceptionChainer()
    catch_exception = no_errors or raise_at_end

    error_msg = 'Some unlinks failed for %s'
    if os.getuid() == 0:
        for link in links:
            with exc.context(catch_exception, error_msg, links):
                try:
                    os.unlink(link)
                except OSError as exc:
                    # Ignore file doesn't exist errors
                    if exc.errno != errno.ENOENT:
                        raise
    else:
        with exc.context(catch_exception, error_msg, links):
            # Ignore file doesn't exist errors
            putils.execute('rm', *links, run_as_root=True,
                           check_exit_code=(0, errno.ENOENT),
                           root_helper=ROOT_HELPER)

    if not no_errors and raise_at_end and exc:
        raise exc


def _execute(*cmd, **kwargs):
    try:
        return rootwrap.custom_execute(*cmd, **kwargs)
    except OSError as e:
        sanitized_cmd = strutils.mask_password(' '.join(cmd))
        raise putils.ProcessExecutionError(
            cmd=sanitized_cmd, description=six.text_type(e))


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

    params['id'] = conn_info['data']['volume_id']
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
    specs.update(state={'choices': ('connected', 'disconnected', 'extended'),
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


def _update_attachment_size(db, vol_id, new_size):
    cursor = db.cursor()
    cursor.execute('UPDATE attachments SET size=%s WHERE id="%s"' %
                   (new_size, vol_id))
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
            module.fail_json(msg='No attachment found')
        return None

    if len(results) > 1:
        module.fail_json(msg='Multiple attachments found')

    return results[0]


def _delete_attachment(db, module):
    query_str = 'DELETE FROM attachments'
    where_str, filters = __generate_where(module.params)
    cursor = db.cursor()
    cursor.execute(query_str + where_str, filters)
    db.commit()
    cursor.close()


def extend_volume(db, module):
    data = _get_data(db, module)
    if not data:
        module.fail_json(msg='No attachment found')
    connector_dict = data['connector']
    conn_info = data[common.CONNECTION_INFO]
    protocol = conn_info['driver_volume_type']
    # NOTE(geguileo): afaik only remotefs uses connection info
    conn = connector.InitiatorConnector.factory(
        protocol, 'sudo', user_multipath=connector_dict['multipath'],
        device_scan_attempts=3, conn=connector_dict)
    new_size = conn.extend_volume(conn_info['data'])
    # Extend returns the size in bytes, convert to GB
    new_size = int(round(new_size / 1024.0 / 1024.0 / 1024.0))

    # Need to update the entry in the database or next connect/disconnect
    # requests will not find it
    _update_attachment_size(db, conn_info['data']['volume_id'], new_size)

    return {'changed': True, 'size': new_size, 'device': data['device']}


def volume(module):
    methods = {'connected': attach_volume,
               'disconnected': detach_volume,
               'extended': extend_volume}
    new_module = _validate_volume(module)
    db = _setup_db(module.params)
    method = methods[new_module.params['state']]
    result = method(db, new_module)
    return result


def node(module):
    specs = module.argument_spec
    specs.update(ips={'type': 'list', 'required': True},
                 multipath={'type': 'bool', 'default': True},
                 enforce_multipath={'type': 'bool', 'default': False})
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

    def my_get_connector_properties(*args, **kwargs):
        if len(args):
            args = list(args)
            args[0] = root_helper
        else:
            kwargs['root_helper'] = root_helper
        kwargs['execute'] = _execute
        return existing_bgcp(*args, **kwargs)

    def my_connector_factory(protocol, *args, **kwargs):
        if len(args):
            # args is a tuple and we cannot do assignments
            args = list(args)
            args[0] = root_helper
        else:
            kwargs['root_helper'] = root_helper
        kwargs['execute'] = _execute

        # OS-Brick's implementation for RBD is not good enough for us
        if protocol == 'rbd':
            factory = RBDConnector
        else:
            factory = functools.partial(existing_bcp, protocol)

        return factory(*args, **kwargs)

    # Replace OS-Brick method and the reference we have to it
    connector.get_connector_properties = my_get_connector_properties
    connector.InitiatorConnector.factory = staticmethod(my_connector_factory)
    if hasattr(rootwrap, 'unlink_root'):
        rootwrap.unlink_root = unlink_root


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
