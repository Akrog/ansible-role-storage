Supported storage
=================

Supported backends are separated by type of storage they provide:

- `Block devices`_
- `Shared filesystems`_
- `Object storage`_

.. _Block devices:

Block devices
~~~~~~~~~~~~~

Currently both Block storage *providers* (*cinderlib* and *cinderclient*)
support the same storage solutions, as they both use the same driver code.  The
biggest difference in terms of backend support is that the *cinderclient*
provider relies on a *Cinder* service deployment, and that's how all the
drivers have been validated by the automated testing system.  The *cinderlib*
provider relies on the *cinderlib* library, which is still in the process of
automating the testing, and for the time being has only been manually validated
with a limited number of backends.

Unless stated otherwise, drivers have not been validated with *cinderlib*,
so even though they should work, they may not.

List of supported drivers in alphabetical order:

- Blockbridge EPS
- Ceph/RBD [2]_
- Coho Data NFS [1]_
- Dell EMC PS
- Dell EMC ScaleIO
- Dell EMC Unity
- Dell EMC VMAX FC
- Dell EMC VMAX iSCSI [2]_
- Dell EMC VNX
- Dell EMC XtremIO FC [2]_
- Dell EMC XtremIO iSCSI [2]_
- Dell Storage Center FC
- Dell Storage Center iSCSI
- DISCO
- DotHill FC
- DotHill iSCSI
- DRBD
- EMC CoprHD FC
- EMC CoprHD iSCSI
- EMC CoprHD ScaleIO
- FalconStor FSS FC
- FalconStor FSS iSCSI
- Fujitsu ETERNUS DX S3 FC
- Fujitsu ETERNUS DX S3 iSCSI
- Generic NFS [1]_
- HGST
- Hitachi HBSD iSCSI
- Hitachi Hitachi NFS [1]_
- Hitachi VSP FC
- Hitachi VSP iSCSI
- HPE 3PAR FC
- HPE 3PAR iSCSI
- HPE LeftHand iSCSI
- HPE MSA FC
- HPE MSA iSCSI
- HPE Nimble FC
- HPE Nimble iSCSI
- Huawei FusionStorage
- Huawei OceanStor FC
- Huawei OceanStor iSCSI
- IBM DS8000
- IBM FlashSystem A9000
- IBM FlashSystem A9000R
- IBM FlashSystem FC
- IBM FlashSystem iSCSI
- IBM GPFS
- IBM GPFS NFS [1]_
- IBM GPFS Remote
- IBM Spectrum Accelerate
- IBM Storwize V7000 FC
- IBM Storwize V7000 iSCSI
- IBM SVC FC
- IBM SVC iSCSI
- IBM XIV
- INFINIDAT InfiniBox
- Infortrend Eonstor DS FC
- Infortrend Eonstor DS iSCSI
- Kaminario K2
- Lenovo FC
- Lenovo iSCSI
- LVM [2]_
- NEC M-Series FC
- NEC M-Series iSCSI
- NetApp 7-mode FC
- NetApp 7-mode iSCSI
- NetApp 7-mode NFS [1]_
- NetApp C-mode FC
- NetApp C-mode iSCSI
- NetApp Data ONTAP NFS [1]_
- NetApp E-Series FC
- NetApp E-Series iSCSI
- NexentaEdge iSCSI
- NexentaEdge NFS [1]_
- NexentaStor iSCSI
- NexentaStor NFS [1]_
- Oracle ZFSSA iSCSI
- Oracle ZFSSA NFS [1]_
- ProphetStor FC
- ProphetStor iSCSI
- Pure FC
- Pure iSCSI
- QNAP iSCSI
- Quobyte USP
- Reduxio
- Sheepdog
- SolidFire [2]_
- Synology iSCSI
- Tegile FC
- Tegile iSCSI
- Tintri
- Veritas Clustered NFS [1]_
- Veritas HyperScale
- Violin V7000 FC
- Violin V7000 iSCSI
- Virtuozzo
- VMware vCenter
- Windows Smbfs
- X-IO ISE FC
- X-IO ISE iSCSI
- XTE iSCSI
- Zadara VPSA iSCSI/iSER


Shared filesystems
~~~~~~~~~~~~~~~~~~

The Storage role has no Shared filesystem provider, so it doesn't support any
backend at the moment.


Object storage
~~~~~~~~~~~~~~

The Storage role has no Object storage provider, so it doesn't support any
backend at the moment.


-------------------------------------------------------------------------------

.. [1] NFS backends that use an image to provide block storage are not
   supported yet.

.. [2] This driver has been validated with *cinderlib* as stated in `its
   documentation
   <https://cinderlib.readthedocs.io/en/latest/validated_backends.html>`_
