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
import os
import sqlite3
import uuid

from ansible.plugins.callback import CallbackBase

__metaclass__ = type
DOCUMENTATION = '''
    callback: storage
    type: aggregate
    short_description: Storage pluging to manage playbook DB
    description:
      - Generates unique ID for the whole playbook run
      - Creates temporary SQLite DB and backends table
      - Cleansup temporary DB on completion
    requirements:
      - none
'''


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'freeloader'
    CALLBACK_NAME = 'storage'
    CALLBACK_NEEDS_WHITELIST = False

    def v2_playbook_on_start(self, playbook):
        self.secret = 'secret'
        self.run_id = uuid.uuid4().hex
        basedir = os.path.realpath(playbook.get_loader().get_basedir())
        self.db_name = os.path.join(basedir,
                                    '.storage-%s.sqlite' % self.run_id)

        self.db = sqlite3.connect(self.db_name)
        self.cursor = self.db.cursor()

        self.cursor.execute('CREATE TABLE IF NOT EXISTS backends (id INTEGER '
                            'PRIMARY KEY, name TEXT, provider TEXT, data '
                            'TEXT, host TEXT, attributes TEXT, ctxt TEXT)')
        self.cursor.execute('CREATE TABLE IF NOT EXISTS providers (name TEXT '
                            'PRIMARY KEY, consumer_data TEXT, '
                            'consumer_module TEXT)')
        self.db.commit()
        self.cursor.close()
        self.db.close()

    def v2_playbook_on_stats(self, stats):
        try:
            os.remove(self.db_name)
        except OSError:
            pass

    def v2_playbook_on_play_start(self, play):
        play.vars['storage_task_info'] = {'run_id': self.run_id,
                                          'db_name': self.db_name,
                                          'secret': self.secret}
