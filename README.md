Storage
=======

The storage role allows you to manage and connect to a large number of storage
solutions from different vendors using an abstracted common interface.  For
example you could create a playbook to provision a volume, connect it to a
host, format it and use it, and use the same playbook on an XtremIO array or a
Ceph cluster just by changing the variables used for the configuration of the
storage controller role.

In order to use this role effectively you must first understand some concepts
like node types, providers, backends, resources, states, and identification of
resources.

Under the storage role you'll find there are two node types, controller and
consumer, this distinction reflects the differences in requirements for the
actions performed by each of these nodes.  A controller node will perform all
management operations like create, delete, extend, map, and unmap volumes for
which will require access to the storage management network and may
additionally require the installation of vendor specific tools or libraries to
do its job.  On the consumer nodes we are only interested in connecting and
disconnecting resources, so we may only require some standard packages such as
iscsi-initiator-tools, but there are still some cases were we may require
specific tools based on the connection type of the volumes, for example for
ScaleIO storage.

A provider is the Ansible module responsible of carrying out operations on the
storage hardware, and one provider must support at least one specific hardware
from a vendor, but it may as well support multiple vendors and a wide range of
storage devices.

Even though there's only two providers at the moment, a large number of storage
vendors and storage backends are supported, as the `cinderlib` provider
leverages the Cinder code (Cinder is the OpenStack block storage service) to
use all storage drivers directly without the need to run the Cinder services
themselves (API, Scheduler, and Volume) and required support services (DBMS and
message broker).

The default implementation is great if we don't have an OpenStack deployment,
but if we already have one we can also use it in our Ansible playbooks using
the `cinderclient` provider to provide storage to nodes outside of the
OpenStack ecosystem.

A backend describes a storage array by providing a specific configuration for a
provider and is identified by a user chosen name.

Resources are the way to represent abstractions within the storage role, such
as backends and volumes (snapshots and shares will follow), and resource states
represent actions we want performed on these resources.

The storage role is modestly smart about locating resources, so in most cases
just a small amount of information is required to reference a resource.  For
example, when deleting a volume, if we only have one backend and one existing
volume associated to a host, then we don't need to provide a backend name, a
volume name, or an id to address it for the purposes of connecting,
disconnecting, or deleting it.

Another important notion we have to remember is that the controller node is
that the controller nodes must be setup before any consumer node and they are
not meant to execute tasks (except the stats gathering) and should be accessed
indirectly from the consumer nodes instead.

Right now this role only supports the following operations:

- Retrieve backend stats
- Create volumes
- Delete volumes
- Attach volumes
- Detach volumes

Even though only block devices are supported at the moment, we intend to
include other resource types like filesystem shares and object storage.

Requirements
------------

- Tested with Ansible >= 2.4.1 but other versions may also work.
- Controller node will install the cinder package from the OSP repository if
  available, and default to the RDO one if not.  It will also install the
  cinderlib python package.
- Consumer node will install os-brick from the OSP repository if available, and
  default to RDO if not.

Configuration
-------------

We must first set up the storage controllers, and they must provide the
following configuration parameters:

- `storage_backends`: A dictionary where the key will be the name of the
  backend and the values will be a provider specific dictionary.  For the
  cinderlib provider the configuration options are the same as the ones
  provided in Cinder for the drivers.

- `storage_$PROVIDER_config`: This would be `storage_cinderlib_config` or
  `storage_cinderclient_config`, and must contain the provider global
  configuration as defined by the provider.  Default values can be found in
  the "vars" directory.

- `storage_$PROVIDER_consumer_config`: This would be
  `storage_cinderlib_consumer_config`, since all existing providers use the
  same consumer code, and sets global consumer configuration options as defined
  by the provider.  Default values can be found in the "vars" directory.

Playbook example
----------------

Assuming we have a "controller" node with an LVM VG called cinder-volumes and a
set of "consumer" nodes that want to attach iSCSI volumes do some operations on
it and then detach and delete them, the following playbook would achieve this:

```

- hosts: storage_controller
  vars:
    storage_backends:
        lvm:
            volume_driver: 'cinder.volume.drivers.lvm.LVMVolumeDriver'
            volume_group: 'cinder-volumes'
            iscsi_protocol: 'iscsi'
            iscsi_helper: 'lioadm'
  roles:
      - { role: storage, node_type: controller }

- hosts: storage_consumers
  roles:
      - { role: storage, node_type: consumer }
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
```

A descriptive explanation of above playbook is:

- Initialize the controller node: Installs required libraries on the controller
- For each consumer node:
  - Install required libraries on the consumer node
  - Create a volume: Created on the controller and associated to consumer
  - Attach the volume created for that node:
    - Controller node maps the volume to the node (other nodes can't connect)
    - Consumer uses iSCSI initiator to attach the volume
  - Display where the volume has been attached
  - Detach the volume:
    - Consumer detaches the volume
    - Controller unmaps the volume

At the time of this writing the consumer role can't auto detect dependencies
based on the connection type of the backends, though this may change in the
future, so any connection specific packages to connect volumes, such as
`iscsi-initiator-utils`, `device-mapper-multipath`, `ceph-common`, etc., need
to be already installed in the system or added via tasks in the playbook.

For additional examples please refer to the playbooks in the "examples"
directory.
