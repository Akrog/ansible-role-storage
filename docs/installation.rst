Installation
============

Like with any other role, before you can use this role in your playbooks you'll
need to install it in the system where the playbooks are going to be run:

.. code-block:: bash

   $ ansible-galaxy install Akrog.storage

Once installed, you can use it in your playbooks.  Usage of the role is covered
in the :doc:`usage` section.

The role has been tested with Ansible >= 2.4.1, but other versions may also
work.


Requirements
------------

Ansible Storage Role providers have specific requirements to manage and
connect to the storage.

The Ansible Storage Role will try to automatically handle all the requirements
for the nodes based on the selected provider and type of node.  This means that
using the storage role on nodes will install packages in order to perform the
node's tasks (manage storage, or consume storage).

.. attention:: Right now requirements management has only been included for
   Fedora, CentOS, and RHEL.

Each storage provider has its own requirements, and they are usually different
for the controller and the consumer nodes.  Being lighter on the consumer
nodes.  Refer to the :doc:`providers section <providers>` for information on
the requirements of each provider.

.. _Consumer requirements:

Consumer requirements
---------------------

At the time of this writing the consumer role can't auto detect dependencies
based on the connection type of the backends.  Though we expect this to change
in the future, at the moment any connection specific packages to connect
volumes, need to be already installed in the system or added via tasks in the
playbook.

Below are some of the packages required to use:

- `Multipathing`_
- `iSCSI`_
- `Ceph/RBD`_

Other connection types will have different requirements.  Please `report an
issue`_ for any missing connection types and we'll add them.

Multipathing
~~~~~~~~~~~~

Block storage multipathing requires package `device-mapper-multipath` to be
installed, configured, and running.  We can do this with a task or in the
command line::

   # yum install device-mapper-multipath
   # mpathconf --enable --with_multipathd y \
   > --user_friendly_names n \
   > --find_multipaths y
   # systemctl enable --now multipathd

Or as Ansible tasks:

.. code-block:: yaml

   - name: Install multipath package
     package:
       name: device-mapper-multipath
       state: present
    become: yes

   - name: Create configuration
     command: mpathconf --enable --with_multipathd y --user_friendly_names n --find_multipaths y
     args:
         creates: /etc/multipath.conf
    become: yes

   - name: Start and enable on boot the multipath daemon
     service:
         name: multipathd
         state: started
         enabled: yes
    become: yes

iSCSI
~~~~~

To use iSCSI we need to install, configure, and run the `iscsi-initiator-utils`
package if it's not already there::

   # yum install iscsi-initiator-utils
   # [ ! -e /etc/iscsi/initiatorname.iscsi ] \
   > && echo InitiatorName=`iscsi-iname` > /etc/iscsi/initiatorname.iscsi
   # systemctl enable --now iscsid

Or as Ansible tasks:

.. code-block:: yaml

   - name: Install iSCSI package
     package:
       name: iscsi-initiator-utils
       state: present
    become: yes

   - name: Create initiator name
     shell: echo InitiatorName=`iscsi-iname` > /etc/iscsi/initiatorname.iscsi
     args:
         creates: /etc/iscsi/initiatorname.iscsi
    become: yes

   - name: Start and enable on boot the iSCSI initiator
     service:
         name: iscsid
         state: started
         enabled: yes
    become: yes

Ceph/RBD
~~~~~~~~

For Ceph/RBD connections we need to install the `ceph-common` package.



.. _report an issue: https://github.com/Akrog/ansible-role-storage/issues/new
