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

import collections
import datetime
import json

from ansible.module_utils import basic
from ansible.module_utils import common


class _SetEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, collections.Set):
            return list(obj)
        elif isinstance(obj, datetime.datetime):
            return obj.isoformat()
        return super(_SetEncoder, self).default(obj)


class Resource(object):
    RESOURCES = {}
    STATES = []
    DEFAULT_STATE = 'present'

    def __init__(self, module, storage_data):
        self.module = module
        self.storage_data = storage_data

    @staticmethod
    def _pop_param(name):
        params = json.loads(basic._ANSIBLE_ARGS.decode('utf-8'))
        param = params['ANSIBLE_MODULE_ARGS'].pop(name, None)
        basic._ANSIBLE_ARGS = json.dumps(params, encoding='utf-8',
                                         cls=_SetEncoder)
        return param

    @staticmethod
    def register(new_class):
        resource = new_class.__name__.lower()
        for name, method in new_class.__dict__.items():
            new_class._set_state(name, method)

        Resource.RESOURCES[resource] = new_class
        return new_class

    @staticmethod
    def state(*args, **kwargs):
        def wrapped(method):
            method.__ansible_state__ = kwargs
            return method

        if args:
            return wrapped(args[0])
        return wrapped

    @classmethod
    def _set_state(cls, state_name, method):
        params = getattr(method, '__ansible_state__', None)
        if params is None:
            return

        cls.STATES.append(state_name)
        if params.get('default'):
            cls.DEFAULT_STATE = state_name

        del method.__dict__['__ansible_state__']

    @classmethod
    def resource_factory(cls):
        params = basic._load_params()
        storage_data = cls._pop_param(common.STORAGE_DATA)

        specs = {'resource': {'choices': list(cls.RESOURCES.keys())},
                 'provider': {'type': 'str', 'choices': ['cinderlib',
                                                         'cinderclient']},
                 'backend': {'type': 'str'}}

        resource = params.get('resource')
        resource_class = cls.RESOURCES.get(resource)
        if resource_class and resource_class.STATES:
            specs['state'] = {'choices': resource_class.STATES,
                              'default': resource_class.DEFAULT_STATE}

        module = basic.AnsibleModule(specs,
                                     check_invalid_arguments=False,
                                     supports_check_mode=False)
        resource = cls.RESOURCES[resource](module, storage_data)
        return resource

    def validate(self):
        # We don't calculate this on init in case we want to do something in
        # the inheriting classes.
        state = self.module.params['state']
        validator = getattr(self, 'validate_' + state, None)
        result = validator() if validator else None
        if not result:
            result = self.module.params
        # Return a modifiable copy
        return result.copy()

    def execute(self, params):
        # We don't calculate this on init in case we want to do something in
        # the inheriting classes.
        params.pop('resource')
        params.pop('provider')
        state = params.pop('state')

        executor = getattr(self, state)
        return executor(params)

    def process(self):
        params = self.validate()
        return self.execute(params)

    def exit(self, *args, **kwargs):
        self.module.exit_json(*args, **kwargs)

    def fail(self, msg, *args, **kwargs):
        kwargs.setdefault('changed', False)
        self.module.fail_json(msg=msg, *args, **kwargs)

    @property
    def running(self):
        return not self.module.check_mode


class Backend(Resource):
    PROVIDER_CONFIG_SPECS = {}
    BACKEND_CONFIG_SPECS = {}

    def validate_present(self):
        specs = self.module.argument_spec.copy()
        specs[common.PROVIDER_CONFIG] = {'type': 'dict',
                                         'options': self.PROVIDER_CONFIG_SPECS,
                                         'required': True}
        specs[common.BACKEND_CONFIG] = {'type': 'dict',
                                        'options': self.BACKEND_CONFIG_SPECS,
                                        'required': True}

        self.module = basic.AnsibleModule(specs, check_invalid_arguments=False)

    def validate_stats(self):
        # We make sure there are no extra params
        specs = self.module.argument_spec
        self.module = basic.AnsibleModule(specs, check_invalid_arguments=True)

    validate_absent = validate_stats


class Volume(Resource):
    def _validate(self, size_required=False, require_id=False, **kwargs):
        specs = self.module.argument_spec.copy()
        specs.update(name={'type': 'str'},
                     id={'type': 'str'},
                     size={'type': 'int', 'required': size_required},
                     host={'type': 'str', 'default': ''},
                     **kwargs)

        required_one_of = []
        if require_id:
            required_one_of.append(('name', 'id'))
        self.module = basic.AnsibleModule(specs,
                                          check_invalid_arguments=True,
                                          required_one_of=required_one_of)

    def validate_present(self):
        self._validate(size_required=True)

    def validate_absent(self):
        self._validate()

    def validate_connected(self):
        self._validate(attached_host={'type': 'str', 'default': ''},
                       connector_dict={'type': 'dict', 'required': True})

    def validate_disconnected(self):
        self._validate(attached_host={'type': 'str'})
