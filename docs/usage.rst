Usage
=====

In this section we'll cover how to use the storage role, the different
operations available, their return values, how to address resources in the
operations, and several examples.

One of the biggest differences between the Storage Role and other roles is that
in this role it is recommended to include your storage tasks on the *consumer*
nodes, even if part of the tasts are actually executed by the *controller*.

Instead of creating a task for the *controller* node to create as many volumes
as *consumer* nodes we have and store the results in variables (or use a naming
template), and then on the *consumer* nodes have a task that attaches one of
those volumes to each node, we just have a task on the *consumers* to create
the volume and connect it.

This way there's no need for variables or naming templates, and the creation
and attaching tasks are together.  This helps simplify the playbooks and the
number of variables we have to move around in our playbooks, resulting in
greater readability.


Configuration
-------------

The role needs to know what type of node we are defining, this is done using
the `node_type` parameter.  Acceptable values are *controller* and *consumer*.
The default being *consumer*.

.. note:: When a node acts as controller and consumer we have to define it as
   two separate role entries.  There is no *controller-consumer* or *all* node
   types.

Here's an example of how to configure a node to be the *controller* and a
*consumer*.

.. code-block:: yaml

   - hosts: storage_controller
     vars:
         [ ... ]
     roles:
         - { role: storage, node_type: controller }
         - { role: storage, node_type: consumer }

For a *controller* node, the role needs to know the *backends* it's going to be
managing in order to set them up.  A single *controller* node can manage
multiple *backends*, which are configured using the `storage_backends`
variable.

The keys of the `storage_backends` dictionary define the IDs of the *backends*
and must be preserved between runs to be able to access previously provisioned
resources.  If we change the *backend* IDs (key in the dictionary) we will no
longer be able to access older resources.

The value part of each entry in the `storage_backends` dictionary corresponds
to another dictionary, this one with the configuration of the specific
*backend*.  The key-value pairs in this dictionary will vary from one
*provider* to another.  The only shared key between them is the `provider` key
used to select the provider we want to use for this backend.

The default value for the `provider` key is `cinderlib`, which is the default
provider.  When using the default value it is common practice to not include
the `provider` key from the configuration.

We can have *backends* from different providers configured on the same
*controller* node.  For example, we can have one using the default provider and
another using the `cinderclient` provider.

.. code-block:: yaml

   - hosts: storage_controller
     vars:
         storage_backends:
             backend1:
                 [ ... ]
             backend2:
                 provider: cinderclient
                 [ ... ]
     roles:
         - { role: storage, node_type: controller }

A list of available parameters we can pass to each provider can be found in the
:doc:`providers' section <providers>`.

.. attention:: *Controller* nodes must always be defined and setup in the
   playbooks before any storage can be used on a consumer node.


Resource addressing
-------------------

In this section we'll cover the rules that are applied by the role to locate
resources for the purposes of idempotency and resource addressing.

The storage role is modestly smart about locating resources, reducing the
amount of information required to pass on task.

Volumes, which are the primary resource available at this moment, have the
following attributes:

- `resource`: Type of the resource, must be `volume`.
- `backend`: Backend id.
- `provider`: Provider for the backend.
- `host`: Who "owns" this backend.
- `id`: UUID for the resource.
- `name`: User defined identifier for the volume.
- `size`: Size of the volume in GBi.

The way providers identify resources is by applying the parameters passed to
tasks as if they were filters.  If the result of applying the filters returns
more than one resource, the provider will return an error.

For single *backend* controllers there's no need to pass `backend` or
`provider` parameters, as they will default to the only configured *backend*.
If we have configured multiple *backends* and at lest one of them is the
default *provider*, then it will default to the first *backend* that was added.
If there are multiple *backends* and none of them uses the default *provider*,
then the role won't be able to determine a default value for these parameters.

Default value for `host` is the FQDN of the consumer node.  Thanks to this, if
we create resources as recommended, in a task on the consumer node, we won't
need to create complicated templates to address volumes when performing tasks
on multiple consumers.

Now that we know the basics of addressing resources it's probably best to have
a look at examples of how it affects operations.  In each one of the
`Operations` we'll present different addressing situations using the *backends*
defined in the previous `Configuration`_ section, where we have 2 *backends*:

- backend1 using the *cinderlib* *provider*.
- backend2 using the *cinderclient* *provider*.


Operations
----------

Create
~~~~~~

The most basic, and most common, operation is creating a volume on a *backend*,
which is accomplished by setting the `state` of a `volume` `resource` to
`present`.  The default `state` for a `volume` is present, so there's no need
to pass it.  There are only 2 required attributes that must be passed on a
create task: `resource` and `size`.

The task provides the following keys in the returned value at the rool level:

=========  ====================================================================
Key        Contents
=========  ====================================================================
`type`     Type of resource. Now it can only be `volume`.
`backend`  ID of the backend where the volume exists.  Matches the key provided
           in `storage_backends`.
`host`     Who "owns" this backend.
`id`       Resource's ID generated by the *provider*.  Most providers use a
           UUID.
`name`     User defined identifier for the volume.
`size`     Size of the volume in GBi.
=========  ====================================================================

Here's the smallest task that can be used to create a volume:

.. code-block:: yaml

   - storage:
         resource: volume
         size: 1

We only have 2 backends, and only one of them uses the default *provider*, so
following the addressing rules the volume will be created on backend1.  This
create task is equivalent to:

.. code-block:: yaml

   - storage:
         resource: volume
         state: present
         size: 1
         backend: backend1
         provider: cinderlib

If we wanted to create the volume on backend2, we would have to specify the
`backend` or the `provider`. Passing the `provider` is also enough as there's
only 1 *backend* for each *provider*:

.. code-block:: yaml

   - storage:
         resource: volume
         size: 1
         backend: backend2

The rest of the parameters will use defaults (`state: present`) or be detected
automatically based on provided parameters (`provider: cinderclient`).

Creating these 2 volumes on the same node doesn't require any additional
parameters as each one is going to different *backends*:

.. code-block:: yaml

   - storage:
         resource: volume
         size: 1

   - storage:
         resource: volume
         size: 1
         backend: backend2

But if we try to do the same to create 2 volumes of the same size on the same
*backend* like this:

.. code-block:: yaml

   - storage:
         resource: volume
         size: 1

   - storage:
         resource: volume
         size: 1

We will end with only 1 volume, as the second call will be considered as a
repeated call by the controller node.  And since these are idempotent
operations no new volume will be created.

To create multiple volumes of the same size on the same *backend* we need to
use the `name` attribute.  Providing it just in one of the tasks is enough, but
we recommend passing it to both:

.. code-block:: yaml

   - storage:
         resource: volume
         size: 1
         name: first-volume

   - storage:
         resource: volume
         size: 1
         name: second-volume

If each one of our volumes has a different size, then we don't need to provide
a name, as one call cannot be mistaken for the other:

.. code-block:: yaml

   - storage:
         resource: volume
         size: 1

   - storage:
         resource: volume
         size: 2

Delete
~~~~~~

Deleting a specific volume is accomplished by setting the `state` of a `volume`
`resource` to `absent`.  And there are no required parameters for this call,
but we can provide as many as we wan to narrow the volume we want to delete to
a single one.

The delete task only returns the `changed` key to reflect whether the volume
was present, and therefore was deleted, or if it wasn't present in the first
place.

To reference a volume for deletion we usually use the same parameters that were
used on the create task.  If we didn't pass any parameters on create, passing
none as well on delete will remove that volume:

.. code-block:: yaml

   - storage:
         resource: volume
         size: 1

   - storage:
         resource: volume
         state: absent

.. warning:: There is no confirmation required to delete a volume, and once the
   volume is deleted it is usually impossible to recover its contents, so we
   recommend specifying as may parameters as possible on deletion tasks.

We don't need to provide the same parameters that we used on the create method
as long as we provide enough information.  We can use the return value from the
create task to do the addressing:

.. code-block:: yaml

   - storage:
         resource: volume
         size: 1
         name: my_volume
         backend: backend2
     register: volume

   - storage:
         resource: volume
         state: absent
         id: "{{volume.id}}"
         backend: "{{volume.backend}}"

.. note:: Keep in mind that there is no global database that stores all the
   resources IDs.  So when using multiple *backends*, even if an ID uniquely
   identifies a resource in all your *backends*, the Storage Role has no way of
   knowing on which *backend* it is, so the task needs enough parameters to
   locate it.  That's why in the example above we pass the `backend` parameter
   to the delete task.

When describin the create task we saw how we could create 2 volumes without a
name because they had different sizes.  If we wanted to remove those volumes we
would have to provide the sizes on the delete task, otherwise the task would
fail because there are 2 volumes that matches the addressing.

.. code-block:: yaml

   - storage:
         resource: volume
         size: 1

   - storage:
         resource: volume
         size: 2

   - storage:
         resource: volume
         state: absent
         size: 1

   - storage:
         resource: volume
         state: absent
         size: 2

Connect
~~~~~~~

Connecting a volume to a node is a multi-step process that requires the
*controller* to export and map the volume to the *consumer* node first, and for
the *consumer* to connect to the volume.  These steps are opaque to the
playbooks, where they are seen as a single task.

Connecting a specific volume to a node is accomplished by setting the `state`
of a `volume` `resource` to `connected`.  There are no specific parameters for
the connect task.  All parameters are used for the addressing of the volume.
Addressing rules explained before apply here.

The task provides the following keys in the returned value at the rool level:

=================  ============================================================
Key                Contents
=================  ============================================================
`changed`          Following standard rules, will be `False` if the volume was
                   already connected, and `True` if it wasn't but now it is.
`type`             Describes the type of device that is connected, which at the
                   moment can only be `block`.
`path`             Path to the device that has been added on the system.
`additional_data`  (Optional) *Provider* specific additional information.
=================  ============================================================

If we only have 1 volume on the node the addressing for the connect task is
minimal.

.. code-block:: yaml

   - storage:
         resource: volume
         size: 1

   - storage:
         resource: volume
         state: connected

Creating and connecting a volume is usually just the first step in our
automation, and following tasks will rely on the `path` key of the returned
value to use the volume on the *consumer* node.

.. code-block:: yaml

   - storage:
         resource: volume
         size: 1
     register: vol

   - storage:
         resource: volume
         state: connected
     register: conn

   - debug:
         msg: "Volume {{vol.id}} is now attached to {{conn.path}}"


Disconnect
~~~~~~~~~~

Disconnecting a volume from a node is a multi-step process that undoes the
steps performed during the connection in reverse.  The *consumer* node detaches
the volume from the node, and then the *controller* unmaps and removes the
exported volume.  These steps are opaque to the playbooks, where they are seen
as a single task.

Disconnecting a specific volume from a node is accomplished by setting the
`state` of a `volume` `resource` to `disconnected`.  There are no specific
parameters for the disconnect task.  All parameters are used for the addressing
of the volume.  Addressing rules explained before apply here.

The disconnect task only returns the `changed` key to reflect whether the
volume was present, and therefore was disconnected, or if it wasn't present in
the first place.

.. note:: Disconnecting a volume will properly flush devices before proceeding
   to detach them.  If it's a multipath device, the multipath will be flushed
   first and then the individual paths.  If flushing is not possible due to
   connectivity issues the volume won't be disconnected.


When we using a single volume the disconnect doesn't need any additional
parameters:

.. code-block:: yaml

   - storage:
         resource: volume
         size: 1

   - storage:
         resource: volume
         state: connected

   - storage:
         resource: volume
         state: disconnected

It's when we have multiple volumes that we have to provide more parameters,
like we do in all the other tasks.

.. code-block:: yaml

   - storage:
         resource: volume
         size: 1

   - storage:
         resource: volume
         size: 1
         backend: backend2

   - storage:
         resource: volume
         backend: backend2
         state: connected

   - storage:
         resource: volume
         backend: backend2
         state: disconnected

Stats
~~~~~

This is the only task that is meant to be executed on the *controller* node.

Stats gathering is a *provider* specific task that return arbitrary data.  Each
provider specifies what information is returned in the :doc:`providers' section
<providers>`, but they must all return this data as the value for the `result`
key.

And example for the default provider:

.. code-block:: yaml

   - storage:
         resource: backend
         backend: lvm
         state: stats
     register: stats

   - debug:
         msg: "Backend {{stats.result.volume_backend_name}} from vendor {{stats.result.vendor_name}} uses protocol {{stats.result.storage_protocol}}"
