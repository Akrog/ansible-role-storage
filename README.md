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

The Storage Role includes support for over 80 block storage drivers out of the box, but 
it can be also be expanded to support additional storage providers.

Thanks to this abstraction it's now possible to write reusable playbooks that
can automate tasks on any of the supported storage arrays.

This allows to manage and consume storage volumes directly on any infrastructure by the 
developer or application owner from any Linux instance.

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
- Use a golden volume for provisioning (volume cloning).
- Resize provisioned volumes.
- Define QoS for provisioned volumes.
- Perform volume migration between backends.


Features
--------

The Storage Role currently supports block storage and has abstracted the
following operations.

- Get *backend* stats
- Create volumes
- Delete volumes
- Attach volumes
- Detach volumes


Getting started
---------------

Let's get you started on running your first Storage playbook.

Running the example playbook will install packages in the system and present a
VG to the system.  We recommend to either run these commands inside a VM or
change the value of the IP variable to the IP of a VM.

After setting up the LVM VG the playbook will create a volume, attach it to the
node via iSCSI, display a message with the device where it has been attached,
detach it, and finally delete the volume.

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

Unlike most real use cases, our example doesn't use a real Storage System.  The
playbook first creates an LVM Volume Group (VG) backed by a device loop.  Using
this VG we can create volumes and export them via iSCSI using the LIO target.


Concepts
--------

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

See more info on usage and configuration in the documentation: 
https://ansible-storage.readthedocs.io/en/docs/