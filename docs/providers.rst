Storage Providers
=================

*Providers* are separated by type of storage they provide:

- `Block storage`_
- `Shared filesystems`_
- `Object storage`_

Block storage
~~~~~~~~~~~~~

The Storage Role currently has 2 block storage *providers*:

- `Cinderlib`_
- `Cinderclient`_

Both use the same storage drivers, supporting the same storage solutions, but
using different approaches.  The :doc:`backends` section provides a detailed
list of supported backends.

The default provider is *cinderlib*, as it doesn't rely on any existing
service.

Cinderlib
---------

The *cinderlib* Storage *provider* uses the *cinderlib* Python library to
leverage existing *Cinder* drivers outside of *OpenStack*, without running any
of the *Cinder* services: API, Scheduler, and Volume.

And when we say that *cinderlib* uses the same drivers as *Cinder*, we don't
mean that these drivers have been copied out of the *Cinder* repository.  We
mean that we install the same `openstack-cinder` package used by the *Cinder*
services, and use the exact same driver code on our *controller* nodes.

Thanks to the *Cinder* package, this *provider* supports a :ref:`considerable
number of different drivers <Block devices>`.  Most of the storage drivers
included in the package don't have external dependencies and can run as they
are.  But there is a small number of drivers that require extra packages or
libraries to manage the storage.

The *cinderlib provider* has the mechanism to automatically install these
packages when deploying a *controller* based on the *backend* configuration.
At this moment the drivers supporting this automatic installation is not
complete, though it is growing.

As we mentioned, the *provider* uses the `openstack-cinder` package, which has
its advantages, but comes with the drawback of requiring more dependencies than
needed, such as the messaging and service libraries.

This, together with the specific driver requirements that we may be using, make
the *cinderlib* provider somewhat heavy in terms of packages being installed.
Making the most common deployment model to have only one *controller* node for
all the consumers.  One way to do it is using the node running the Ansible
engine as the controller.

There is only 1 fixed parameter that the *cinderlib provider* requires:

===============  ==============================================================
Key              Contents
===============  ==============================================================
`volume_driver`  Namespace of the driver.
===============  ==============================================================

All other parameters depend on the driver we are using, and we recommend
looking into the `specific driver configuration`_ page for more information on
what these parameters are.  If the driver has been validated for the
*cinderlib* library we can see which parameters where used in `its
documentation`_.

Here is an example for XtremIO storage:

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

When working with the *cinderlib* provider there's one thing we must be aware
of, the metadata persistence.

*Cinder* drivers are not required to be stateless, so most of them store
metadata in the *Cinder* database to reduce the number of queries to the
storage backend.

Since we use the *Cinder* drivers as they are, we cannot be stateless either.
We'll use the metadata persistence plugin mechanism to store the driver's
information.  At this moment there's only one plugin available, the database
one, allowing us to store the metadata in many different database engines.

.. attention::

   If the metadata is lost, then the *cinderlib* role will no longer be able to
   use any of the resource it has created.

   Proper care is recommended when deciding where to store the metadata.  It
   can be stored in an external database, in a replicated shared filesystem,
   etc.

The default configuration is to store it in a SQLite file called
`storage_cinderlib.sqlite` in the SSH user's home directory:

.. code-block:: yaml

   storage_cinderlib_persistence:
       storage: db
       connection: sqlite:///storage_cinderlib.sqlite

But we can change it to use other databases passing the connection information
using `SQLAlchemy database URLs format`_ in the `connection` key.

For example we could use a MySQL database:

.. code-block:: yaml

   - hosts: storage_controller
     vars:
       storage_cinderlib_persistence:
           storage: db
           connection: mysql+pymysql://root:stackdb@127.0.0.1/cinder?charset=utf8

In the future there will be more metadata persistence plugins, and they will be
referenced in *cinderlib*'s `metadata persistence plugins documentation`_.

Having covered the *controller* nodes, we'll now look into the *consumer*
nodes.

The *consumer* code is executed on a *consumer* node when we want to connect or
disconnect a volume to the node.  To achieve this it implements 3 functions:

- Connect volume.
- Disconnect volume.
- Get connector information for the node.

Please have a look at the :ref:`Consumer requirements` section for relevant
information on the dependencies for connections on the *consumer* node.

Connection and disconnections are mostly managed using the `OS-Brick`_.
Although there are some exceptions like for Ceph/RBD connections where we
manage them ourselves.

To speed things when we receive a call to connect a volume that's already
connected, we use a simple SQLite database.  This may change in the future.

This database is stored by default on the SSH user's home using filename
`storage_cinderlib_consumer.sqlite`.  But we can change the location with the
`storage_cinderlib_consumer_defaults` variable.  Default configuration is:

.. code-block:: yaml

   storage_cinderlib_consumer_defaults:
     db_file: storage_cinderlib_consumer.sqlite

.. note::

   In future releases the use of the SQLite database on the *consumer* may be
   removed.


Cinderclient
------------

The *cinderclient* Storage *provider* wraps an *OpenStack Cinder* service to
expose it in Ansible using the Storage Role abstraction.

Communication between the Storage *provider* and the *Cinder* service is
accomplished via *Cinder*'s well defined REST API.

Relying on an external *Cinder* service to manage our block storage greatly
reduces the dependencies required by the *controller* nodes.  The only
dependency is the *python2-cinderclient* package, making *controllers* for the
*cinder provider* very light.

With this *provider*, deploying all our nodes as *controller* and *consumer*
makes sense.

The *cinderclient provider* needs the following configuration parameters to
connect to a *Cinder* service:

==============  ===============================================================
Key             Contents
==============  ===============================================================
`username`      *OpenStack* user name.
`password`      Password for *OpenStack* user.
`project_name`  *OpenStack* project/tenant name.
`region_name`   *OpenStack* region name.
`auth_url`      URL for the authentication endpoint.
`volume_type`   *Cinder* volume type to use.  When left undefined *provider*
                will use *Cinder*'s default volume type.
==============  ===============================================================

There are no global configuration options for the *cinderclient provider*, so
values stored in the `storage_cinderclient_defaults` variable won't be used.

.. note::

   Current implementation only supports *Cinder* services that use *Keystone*
   as the identity service.  Standalone *Cinder* is not currently supported.

Here's a configuration example for the *cinderclient provider* showing how to
use the default volume type from *Cinder*:

.. code-block:: yaml

   - hosts: storage_controller
     vars:
       storage_backends:
           default:
               provider: cinderclient
               password: nomoresecret
               auth_url: http://192.168.1.22/identity
               project_name: demo
               region_name: RegionOne
               username: admin
     roles:
         - {role: storage, node_type: controller}

Using a specific volume type is very easy, we just need to add the
`volume_type` parameter:

.. code-block:: yaml
   :emphasize-lines: 11

   - hosts: storage_controller
     vars:
       storage_backends:
           default:
               provider: cinderclient
               password: nomoresecret
               auth_url: http://192.168.1.22/identity
               project_name: demo
               region_name: RegionOne
               username: admin
               volume_type: ceph
     roles:
         - {role: storage, node_type: controller}


Since the *cinderclient* and *cinderlib providers* use the same storage driver
code, the connection information to the storage obtained by the *controller*
node follows the same format.  Since the connection information is the same,
both *providers* use the same *consumer* library code to present the storage on
the *consumer* node.  Please refer to the `Cinderlib`_ provider section for
more information on this *consumer* module.

.. note::

   Managed resources will be visible within *OpenStack*, and therefore can be
   managed using *Horizon* (the web interface), or the *cinderclient* command
   line.  We don't recommend mixing management tools, so it'd be best to only
   manage Storage Role resources using Ansible.  To help isolate our resources
   we recommend using a specific tenant for the Storage Role.


Shared filesystems
~~~~~~~~~~~~~~~~~~

There are no Shared filesystem providers at the moment.


Object storage
~~~~~~~~~~~~~~

There are no Object storage providers at the moment.



.. _specific driver configuration: https://docs.openstack.org/cinder/latest/configuration/block-storage/volume-drivers.html
.. _metadata persistence plugins documentation: https://cinderlib.readthedocs.io/en/latest/topics/metadata.html
.. _its documentation: https://cinderlib.readthedocs.io/en/latest/validated_backends.html
.. _SQLAlchemy database URLs format: http://docs.sqlalchemy.org/en/latest/core/engines.html#database-urls
.. _OS-Brick: https://github.com/openstack/os-brick
