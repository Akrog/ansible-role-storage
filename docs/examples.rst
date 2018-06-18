Examples
========

On the :doc:`introduction` and :doc:`usage` sections we provided some examples
and snippets.  Here we'll provide larger examples to show the specifics of some
backends, some interesting concepts, and advanced usage:


Kaminario backend
~~~~~~~~~~~~~~~~~

In this example we'll see how to configure the Kaminario K2 backend on a
*controller* node using the default `cinderlib` provider.

.. note:: The Kaminario backend requires the `krest` PyPi package to be
   installed on the *controller*, but we don't need to worry about it, because
   the `cinderlib` provider takes care of it during the role setup.

.. code-block:: yaml

   - hosts: storage_controller
     vars:
       storage_backends:
           kaminario:
               volume_driver: cinder.volume.drivers.kaminario.kaminario_iscsi.KaminarioISCSIDriver
                 san_ip: w.x.y.z
                 san_login: admin
                 san_password: nomoresecrets
     roles:
         - { role: storage, node_type: controller }


Populating data
~~~~~~~~~~~~~~~

Some applications may require specific data to be present in the system before
they are run.

Thanks to the Storage Role we can easily automate the deployment of our whole
application with custom configuration in an external disk:

- Install the application.
- Create a volume.
- Connect the volume.
- Format the volume.
- Populate the default configuration and data.
- Enable and start our application.

.. code-block:: yaml

   - hosts: storage_consumers
     roles:
         - {role: storage, node_type: consumer}
     tasks:
         - name: Install our application
           package:
               name: my-app
               state: present

         - name: Create the volume
           storage:
               resource: volume
               size: 20

         - name: Connect the volume
           storage:
               resource: volume
               state: connected
           register: conn

         - name: Format the disk
           filesystem:
               fstype: ext4
               dev: "{{conn.path}}"
           become: yes

         - name: Mount the disk
           mount:
               path: /mnt/my-app-data
               src: "{{conn.path}}"
               fstype: ext4
               mode: 0777
           become: yes

         - name: Get default configuration and data
           unarchive:
               remote_src: yes
               src: https://mydomain.com/initial-data.tar.gz
               dest: /mnt/my-app-data
               owner: myapp
               group: myapp
           creates: /mnt/my-app-data/lib

         - name: Link the data to the disk contents
           file:
               src: /mnt/my-app-data/lib
               dest: /var/lib/my-app
               owner: myapp
               group: myapp
               state: link

         - name: Link the configuration to the disk contents
           file:
               src: /mnt/my-app-data/etc
               dest: /etc/my-app
               owner: myapp
               group: myapp
               state: link

         - name: Enable and start the service
           service:
               enabled: yes
               name: my-app
               state: started


Ceph backend
~~~~~~~~~~~~

Unlike other *backends*, the Ceph/RBD backend does not receive all the
*backend* configuration and credentials via parameters.  It needs 2
configuration files present on the *controller* node, and the parameters must
point to these files.  The role doesn't know if these configuration files are
already present on the *controller* node, if they must be copied from the
Ansible controller, or from some other locations, so it's our responsibility to
copy them to the *controller* node.

.. note:: The Ceph/RBD backend requires the `ceph-common` package to be
   installed on the *controller*, but we don't need to worry about it, because
   the `cinderlib` provider takes care of it during the role setup.

Contents of our `ceph.conf` file:

.. code-block:: ini

   [global]
   fsid = fb86a5b7-6473-492d-865c-60229c986b8a
   mon_initial_members = localhost.localdomain
   mon_host = 192.168.1.22
   auth_cluster_required = cephx
   auth_service_required = cephx
   auth_client_required = cephx
   filestore_xattr_use_omap = true
   osd crush chooseleaf type = 0
   osd journal size = 100
   osd pool default size = 1
   rbd default features = 1

Contents of our `ceph.client.cinder.keyring` file:

.. code-block:: ini

   [client.cinder]
           key = AQAj7eZarZzUBBAAB72Q6CjCqoftz8ISlk5XKg==

Here's how we would setup our *controller* using these files:

.. code-block:: yaml

   - hosts: storage_controller
     tasks:
         - file:
               path=/etc/ceph/
               state=directory
               mode: 0755
           become: yes
         - copy:
               src: ceph.conf
               dest: /etc/ceph/ceph.conf
               mode: 0644
           become: yes
         - copy:
               src: ceph.client.cinder.keyring
               dest: /etc/ceph/ceph.client.cinder.keyring
               mode: 0600
               owner: vagrant
               group: vagrant
           become: yes

   - hosts: storage_controller
     vars:
       storage_backends:
           ceph:
               volume_driver: cinder.volume.drivers.rbd.RBDDriver
               rbd_user: cinder
               rbd_pool: volumes
               rbd_ceph_conf: /etc/ceph/ceph.conf
               rbd_keyring_conf: /etc/ceph/ceph.client.cinder.keyring
     roles:
         - {role: storage, node_type: controller}

.. note:: The storage role runs a minimum check on the *backend* during setup,
   so we need to have the configuration files present before setting up the
   role.

By default, the RBD client looks for the keyring under `/etc/ceph/` regardless
of the configuration of the `rbd_keyring_conf` for the *backend*.  If we want
to have the keyring in another location we need to point it in the
`cinder.conf` file.

Here's an example of how to store the keyring file out of the `/etc/ceph`
directory.

.. code-block:: yaml

   - hosts: storage_controller
     tasks:
         - file:
               path=/home/vagrant/ceph
               state=directory
               owner=vagrant
               group=vagrant
         - copy:
               src: ceph.conf
               dest: /home/vagrant/ceph/ceph.conf
         - copy:
               src: ceph.client.cinder.keyring
               dest: /home/vagrant/ceph/ceph.client.cinder.keyring
         - ini_file:
               dest=/home/vagrant/ceph/ceph.conf
               section=global
               option=keyring
               value=/home/vagrant/ceph/$cluster.$name.keyring

   - hosts: storage_controller
     vars:
       storage_backends:
           ceph:
               volume_driver: cinder.volume.drivers.rbd.RBDDriver
               rbd_user: cinder
               rbd_pool: volumes
               rbd_ceph_conf: /home/vagrant/ceph/ceph.conf
               rbd_keyring_conf: /home/vagrant/ceph/ceph.client.cinder.keyring
     roles:
         - {role: storage, node_type: controller}

.. attention:: Even if we are setting they `keyring` in the `ceph.conf` file we
   must always pass the right `rbd_keyring_conf` parameter or we won't be able
   to attach from non controller nodes.


Bulk create
~~~~~~~~~~~

One case were we would be running a creation task on the controller would be
if we want to have a pool of volumes at our disposal.

In this case we'll want to keep the `host` empty so it doesn't get the
*controller* node's FQDN.

Here's an example creating 50 volumes of different sizes:

.. code-block:: yaml

   - hosts: storage_controller
     vars:
         num_disks: 50
         storage_backends:
             lvm:
                 volume_driver: 'cinder.volume.drivers.lvm.LVMVolumeDriver'
                 volume_group: 'cinder-volumes'
                 iscsi_protocol: 'iscsi'
                 iscsi_helper: 'lioadm'
     roles:
         - {role: storage, node_type: controller}
     tasks:
         - name: "Create {{num_disks}} volumes"
           storage:
               resource: volume
               state: present
               name: "mydisk{{item}}"
               host: ''
               size: "{{item}}"
           with_sequence: start=1 end={{num_disks}}

When using this kind of volumes we have to be careful with the addressing,
because an undefined `host` parameter will default to the node's FQDN, which
won't match the created volumes.

We can use the `name` parameter to connect to a volume, or we can use the size,
size they are all of different sizes.

.. code-block:: yaml

   - hosts: web_server
     roles:
         - {role: storage, node_type: consumer}
     tasks:
         - storage:
               resource: volume
               state: connected
               host: ''
               size: 20
           register: conn


Migrating data
~~~~~~~~~~~~~~

There may come a time when we want to migrate a volume from one *backend* to
another.  For example when moving volumes from a local testing *backend* to a
real backend.

There are at least two ways of doing it, copying the whole device, or mounting
the system and synchronizing the contents.

For simplicity we'll only cover the easy case of copying the whole device,
which works fine when the destination is a thick volume.  If the destination is
a thin volume we would be wasting space.

.. code-block:: yaml

   - hosts: storage_controller
     vars:
         storage_backends:
             lvm:
                 volume_driver: 'cinder.volume.drivers.lvm.LVMVolumeDriver'
                 volume_group: 'cinder-volumes'
                 iscsi_protocol: 'iscsi'
                 iscsi_helper: 'lioadm'
             kaminario:
               volume_driver: cinder.volume.drivers.kaminario.kaminario_iscsi.KaminarioISCSIDriver
               san_ip: w.x.y.z
               san_login: admin
               san_password: nomoresecrets
     roles:
         - {role: storage, node_type: controller}

   - hosts: storage_consumer
     tasks:
         - name: Retrieve the existing volume information
           storage:
               resource: volume
               backend: lvm
               state: present
               name: data-disk
           register: vol

         - name: Create a new volume on the destination backend using the source information.
           storage:
               resource: volume
               backend: kaminario
               state: present
               name: "{{vol.name}}"
               size: "{{vol.size}}"
               host: "{{vol.host}}"
           register: new_vol

         - storage:
               resource: volume
               backend: lvm
               state: connected
               id: "{{vol.id}}"
           register: conn

         - storage:
               resource: volume
               backend: kaminario
               state: connected
               id: "{{new_vol.id}}"
           register: new_conn

         - name: Copy the data
           command: "dd if={{conn.path}} of={{new_conn.path}} bs=1M"
           become: true

         - storage:
               resource: volume
               backend: lvm
               state: disconnected
               id: "{{vol.id}}"

         - storage:
               resource: volume
               backend: kaminario
               state: disconnected
               id: "{{new_vol.id}}"
