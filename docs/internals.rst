Internals
=========

In this section we'll go over the Storage Role internals to explain the
architecture, flows, and other implementation details.

This information should help debug issues on existing roles, and provide
details on how to implement new roles.

.. warning:: This section is still in an early conceptualization phase, so it's
   not worth reading.

.. todo:: Do this whole section

Topics to cover:

- Installation tasks for the providers.
- Driver specific installation tasks for the *cinderlib* *provider*.
- How we send work to a *controller* when requested on the *consumer*.
- How we separate methods on the *controller* and *consumer* code.
- Data returned by the different method on the *controller* and *consumer*.
- How to create a new provider using `storage_base.py` classes.
- How a *provider* can reuse the *cinderlib* *consumer* code.
- Describe workarounds that have been implemented using callback and lookup
  plugins.
- Explain why the work was split between consumer and controller:

  - less requirements on consumer nodes
  - consumers don't need access to the management network
  - reuse consumer code/requirements

- Example of a workflow for attach or detach.

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

This will create a volume for each consumer host and attach it to the node,
then display the path where it has been connected before proceeding to
disconnect and delete it.

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
