Introduction
============

The Ansible Storage Role is a vendor agnostic abstraction providing
infrastructure administrators with automation for storage solutions and to
access provisioned resources.

Thanks to this abstraction it's now possible to write reusable playbooks that
can automate tasks on any of the supported storage arrays.

The role will provide an abstraction for multiple storage types:

- *Block* storage.
- *Shared* filesystems.
- *Object* storage.

Use cases:

- Automate provisioning of volumes for:

  - Bare metal hosts.
  - VMs managed via the `virt Ansible module
    <https://docs.ansible.com/ansible/latest/modules/virt_module.html>`_.
  - VMs managed on oVirt, OpenStack, and VMWare.
  - Cloud providers.

- Take periodical snapshots of provisioned volumes.


Features
--------

At the moment the only supported storage type is *Block* storage, with a
limited number of features:

- Get *backend* stats
- Create volumes
- Delete volumes
- Extend volumes
- Attach volumes
- Detach volumes

There are plans to add new features and provider for new storage types.  Refer
to the :doc:`todo` section for information on the plans for the role.


Concepts
--------

The Storage Role includes support for over 80 block storage drivers out of the
box with the :doc:`default provider <providers/cinderlib>`, and this list can
be expanded even further with new storage providers.

A provider is the Ansible module responsible for carrying out operations on the
storage hardware.  Each provider must support at least one specific hardware
from a vendor, but it may as well support more, like the default provider does.

Even though there are only two providers at the moment, they support a large
number of different storage vendors and storage backends.

To expose the functionality of these providers, the Storage Role introduces the
concept of *backends*.  A *backend* is constructed passing a specific
configuration to a provider in order to manage a specific storage hardware.

There are two types of nodes in the Storage Role, *controllers* and
*consumers*.

.. figure:: _static/ansible_diagram.svg
   :align: center

   Ansible Storage Role nodes diagram

*Controllers* have access to the storage management network and know how to
connect to the storage hardware management interface and control it.  For
example to create and export a volume.

*Consumers* only need access to the storage data network in order to connect
to the resources we have provisioned.  For example to connect a volume via
iSCSI.

.. _intro_config:

Configuration
-------------

Before we can provision or use our storage, we need to setup the *controller*
node, the one that will manage our storage.

There are two types of configuration options: One provides global configuration
options for the provider, and the other provides the configuration required to
access the storage's management interface.

In both cases the valid contents for these configuration parameters depend on
the provider being used, as each provider has different options.

The names of the parameters are:

- `storage_backends` is a dictionary providing the configuration for all the
  *backends* we want the controller node to manage.

- `storage_$PROVIDER_config` and `storage_$PROVIDER_consumer_config` are the
  global provider configuration options to over-ride the defaults.  Providers
  are expected to provide sensible defaults to avoid users having to change
  these.

All the information related to these configuration options is available on the
:doc:`providers' section <providers>`, but here's an example of how to setup a
node to manage an XtremIO array:

.. code-block:: yaml

   - hosts: storage_controller
     vars:
       storage_backends:
         xtremio:
           volume_driver: cinder.volume.drivers.dell_emc.xtremio.XtremIOISCSIDriver
           san_ip: w.x.y.z
           xtremio_cluster_name: CLUSTER-NAME
           san_login: admin
           san_password: nomoresecrets
     roles:
         - {role: storage, node_type: controller}


Example
-------

Assuming our playbook has already been configured a backend on the controller
node, for example like we did above, we can proceed to use this backend to
provision and use the volumes like this:

.. code-block:: yaml

   - hosts: storage_consumers
     roles:
         - {role: storage, node_type: consumer}
     tasks:
         - name: Create volume
           storage:
               resource: volume
               state: present
               size: 1
           register: vol

         - name: Connect volume
           storage:
               resource: volume
               state: connected
           register: conn

         - debug:
             msg: "Volume {{ vol.id }} attached to {{ conn.path }}"

         - name: Disconnect volume
           storage:
               resource: volume
               state: disconnected

         - name: Delete volume
           storage:
               resource: volume
               state: absent
