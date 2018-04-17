# (c) 2017 Ansible Project
# GNU General Public License v3.0+ (https://www.gnu.org/licenses/gpl-3.0.txt)
from __future__ import (absolute_import, division, print_function)

from ansible import errors
from ansible.module_utils.six import string_types
from ansible.plugins import lookup

__metaclass__ = type

DOCUMENTATION = """
    lookup: vars
    author: Ansible Core
    version_added: "2.4"
    short_description: Return first found variable
    description:
      - Retrieves the value of the first Ansible variable found.
      - Based on the vars lookup plugin from Ansible core 2.5
    options:
      _term:
        description: The variable names to look up.
        required: True
"""

EXAMPLES = """
- name: Show value of 'variablename' or 'variablename_2'
  debug: msg="{{ lookup('vars', 'variabl' + myvar, 'variabl' + myvar + '_2')}}"
  vars:
    variablename: hello
    myvar: ename
"""

RETURN = """
_value:
  description:
    - valueof the variables requested.
"""


class LookupModule(lookup.LookupBase):

    def run(self, terms, variables=None, **kwargs):
        if variables is not None:
            self._templar.set_available_variables(variables)
        myvars = getattr(self._templar, '_available_variables', {})

        for term in terms:
            if not isinstance(term, string_types):
                raise errors.AnsibleError('Invalid setting identifier, "%s" '
                                          'is not a string, its a %s' %
                                          (term, type(term)))

            if term in myvars:
                value = myvars[term]
            elif 'hostvars' in myvars and term in myvars['hostvars']:
                # maybe it is a host var?
                value = myvars['hostvars'][term]
            else:
                continue
            result = self._templar.template(value, fail_on_undefined=True)
            return [result]

        raise errors.AnsibleUndefinedVariable('No variable found with name: '
                                              '%s' % term)
