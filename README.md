<p align="center">
  <img src ="./docs/_static/ansible_role_storage.png" />
</p>

Ansible Storage Role
====================

[![Docs](https://readthedocs.org/projects/ansible-storage/badge/?version=master)](https://ansible-storage.readthedocs.io)
[![Galaxy](https://img.shields.io/badge/galaxy-Akrog.storage-blue.svg?style=flat-square)](https://galaxy.ansible.com/Akrog/storage/)

The Ansible Storage Role is a vendor agnostic abstraction providing
infrastructure administrators with automation for storage solutions and to
access provisioned resources.

Thanks to this abstraction it's now possible to write reusable playbooks that
can automate tasks on any of the supported storage arrays.

The role will provide an abstraction for multiple storage types:

- Block storage.
- Shared filesystems.
- Object storage.

Use cases:

- Automate provisioning of volumes for:
  - Bare metal hosts.
  - VMs managed via the [virt Ansible module](
    https://docs.ansible.com/ansible/latest/modules/virt_module.html).
  - VMs managed on oVirt, OpenStack and VMWare.
  - Cloud providers.
- Take periodical snapshots of provisioned volumes.


Features
--------

The Storage Role currently supports block storage and has abstracted the
following operations.

- Get *backend* stats
- Create volumes
- Delete volumes
- Attach volumes
- Detach volumes


Concepts
--------

The Storage Role includes support for over 80 block storage drivers out of the
box, but this can be expanded creating a new storage provider.

A provider is the Ansible module responsible for carrying out operations on the
storage hardware.  Each provider must support at least one specific hardware
from a vendor, but it may as well support more, like the default provider does.

To expose the functionality of these providers, the Storage Role introduces the
concept of *backends*.  A *backend* is constructed passing a specific
configuration to a provider in order to manage a specific storage hardware.

There are two types of nodes in the Storage Role, *controllers* and
*consumers*.

<p align="center">
  <img src ="./docs/_static/ansible_diagram.svg" />
</p>

*Controllers* have access to the storage management network and know how to
connect to the storage hardware management interface and control it.  For
example to create and export a volume.

*Consumers* only need access to the storage data network in order to connect
to the resources we have provisioned.  For example to connect a volume via
iSCSI.

Getting started
---------------

Let's get you started on running your first Storage playbook.

Unlike most real use cases, our example doesn't use a real Storage System.  The
playbook first creates an LVM Volume Group (VG) backed by a device loop.  Using
this VG we can create volumes and export them via iSCSI using the LIO target.

The playbook will not differentiate between *controller* and *consumer* nodes,
deploying everything in a single node.

After setting up the LVM VG the playbook will create a volume, attach it to the
node via iSCSI, display a message with the device where it has been attached,
detach it, and finally delete the volume.

Running the example playbook will install packages in the system and present a
VG to the system.  We recommend to either run these commands inside a VM or
change the value of the IP variable to the IP of a VM.

To run the playbook we'll first need to install the role.

``` bash
$ ansible-galaxy install Akrog.storage
```

Once we have installed the role we can go ahead and run the role.

There are many ways to run a playbook, for simplicity here we'll just
illustrate how to run it on the local host using our user and assuming we have
`sshd` enabled, our own `~/.ssh/id_rsa` in the `~/.ssh/authorized_keys` file,
and our user can run `sudo` commands without password.

``` bash
$ IP=127.0.0.1
$ cd ~/.ansible/roles/Akrog.storage/example
$ ansible-playbook -i $IP, lvm-backend.yml
```

Configuration
-------------

Before we can provision or use our storage, we need to setup the *controller*
node.

There are several configuration options that allow us to change default global
configuration for a provider's *controller* and *consumer* modules.  For now
we'll assume they have sensible defaults, so we'll only look at the
`storage_backends` configuration variable passed to the Storage Role.

The `storage_backends` is a dictionary providing the configuration for all the
*backends* we want a *controller* node to manage.  They keys of the dictionary
will be the identifiers for the *backends*, and they must be unique.

Example of how we can setup a node to manage an XtremIO array:

``` yml
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
```

Example
-------

Now that we have configured the *controller* node, we can start using the
*backend*, for example to provision and attach a new volume for each of our
consumer nodes:

``` yml
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
```
