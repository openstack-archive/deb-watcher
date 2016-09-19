..
      Except where otherwise noted, this document is licensed under Creative
      Commons Attribution 3.0 License.  You can view the license at:

          https://creativecommons.org/licenses/by/3.0/

=============================================
Set up a development environment via DevStack
=============================================

Watcher is currently able to optimize compute resources - specifically Nova
compute hosts - via operations such as live migrations. In order for you to
fully be able to exercise what Watcher can do, it is necessary to have a
multinode environment to use.

You can set up the Watcher services quickly and easily using a Watcher
DevStack plugin. See `PluginModelDocs`_ for information on DevStack's plugin
model. To enable the Watcher plugin with DevStack, add the following to the
`[[local|localrc]]` section of your controller's `local.conf` to enable the
Watcher plugin::

    enable_plugin watcher git://git.openstack.org/openstack/watcher

For more detailed instructions, see `Detailed DevStack Instructions`_. Check
out the `DevStack documentation`_ for more information regarding DevStack.

.. _PluginModelDocs: http://docs.openstack.org/developer/devstack/plugins.html
.. _DevStack documentation: http://docs.openstack.org/developer/devstack/

Detailed DevStack Instructions
==============================

#. Obtain N (where N >= 1) servers (virtual machines preferred for DevStack).
   One of these servers will be the controller node while the others will be
   compute nodes. N is preferably >= 3 so that you have at least 2 compute
   nodes, but in order to stand up the Watcher services only 1 server is
   needed (i.e., no computes are needed if you want to just experiment with
   the Watcher services). These servers can be VMs running on your local
   machine via VirtualBox if you prefer. DevStack currently recommends that
   you use Ubuntu 14.04 LTS. The servers should also have connections to the
   same network such that they are all able to communicate with one another.

#. For each server, clone the DevStack repository and create the stack user::

       sudo apt-get update
       sudo apt-get install git
       git clone https://git.openstack.org/openstack-dev/devstack
       sudo ./devstack/tools/create-stack-user.sh

   Now you have a stack user that is used to run the DevStack processes. You
   may want to give your stack user a password to allow SSH via a password::

       sudo passwd stack

#. Switch to the stack user and clone the DevStack repo again::

       sudo su stack
       cd ~
       git clone https://git.openstack.org/openstack-dev/devstack

#. For each compute node, copy the provided `local.conf.compute`_ example file
   to the compute node's system at ~/devstack/local.conf. Make sure the
   HOST_IP and SERVICE_HOST values are changed appropriately - i.e., HOST_IP
   is set to the IP address of the compute node and SERVICE_HOST is set to the
   IP address of the controller node.

   If you need specific metrics collected (or want to use something other
   than Ceilometer), be sure to configure it. For example, in the
   `local.conf.compute`_ example file, the appropriate ceilometer plugins and
   services are enabled and disabled. If you were using something other than
   Ceilometer, then you would likely want to configure it likewise. The
   example file also sets the compute monitors nova configuration option to
   use the CPU virt driver. If you needed other metrics, it may be necessary
   to configure similar configuration options for the projects providing those
   metrics.

#. For the controller node, copy the provided `local.conf.controller`_ example
   file to the controller node's system at ~/devstack/local.conf. Make sure
   the HOST_IP value is changed appropriately - i.e., HOST_IP is set to the IP
   address of the controller node.

   Note: if you want to use another Watcher git repository (such as a local
   one), then change the enable plugin line::

       enable_plugin watcher <your_local_git_repo> [optional_branch]

   If you do this, then the Watcher DevStack plugin will try to pull the
   python-watcherclient repo from <your_local_git_repo>/../, so either make
   sure that is also available or specify WATCHERCLIENT_REPO in the local.conf
   file.

   Note: if you want to use a specific branch, specify WATCHER_BRANCH in the
   local.conf file. By default it will use the master branch.

#. Start stacking from the controller node::

       ./devstack/stack.sh

#. Start stacking on each of the compute nodes using the same command.

#. Configure the environment for live migration via NFS. See the
   `Multi-Node DevStack Environment`_ section for more details.

.. _local.conf.controller: https://github.com/openstack/watcher/tree/master/devstack/local.conf.controller
.. _local.conf.compute: https://github.com/openstack/watcher/tree/master/devstack/local.conf.compute

Multi-Node DevStack Environment
===============================

Since deploying Watcher with only a single compute node is not very useful, a
few tips are given here for enabling a multi-node environment with live
migration.

Configuring NFS Server
----------------------

If you would like to use live migration for shared storage, then the controller
can serve as the NFS server if needed::

    sudo apt-get install nfs-kernel-server
    sudo mkdir -p /nfs/instances
    sudo chown stack:stack /nfs/instances

Add an entry to `/etc/exports` with the appropriate gateway and netmask
information::

    /nfs/instances <gateway>/<netmask>(rw,fsid=0,insecure,no_subtree_check,async,no_root_squash)

Export the NFS directories::

    sudo exportfs -ra

Make sure the NFS server is running::

    sudo service nfs-kernel-server status

If the server is not running, then start it::

    sudo service nfs-kernel-server start

Configuring NFS on Compute Node
-------------------------------

Each compute node needs to use the NFS server to hold the instance data::

    sudo apt-get install rpcbind nfs-common
    mkdir -p /opt/stack/data/instances
    sudo mount <nfs-server-ip>:/nfs/instances /opt/stack/data/instances

If you would like to have the NFS directory automatically mounted on reboot,
then add the following to `/etc/fstab`::

    <nfs-server-ip>:/nfs/instances /opt/stack/data/instances nfs auto 0 0

Edit `/etc/libvirt/libvirtd.conf` to make sure the following values are set::

    listen_tls = 0
    listen_tcp = 1
    auth_tcp = "none"

Edit `/etc/default/libvirt-bin`::

    libvirtd_opts="-d -l"

Restart the libvirt service::

    sudo service libvirt-bin restart

Setting up SSH keys between compute nodes to enable live migration
------------------------------------------------------------------

In order for live migration to work, SSH keys need to be exchanged between
each compute node:

1. The SOURCE root user's public RSA key (likely in /root/.ssh/id_rsa.pub)
   needs to be in the DESTINATION stack user's authorized_keys file
   (~stack/.ssh/authorized_keys). This can be accomplished by manually
   copying the contents from the file on the SOURCE to the DESTINATION. If
   you have a password configured for the stack user, then you can use the
   following command to accomplish the same thing::

        ssh-copy-id -i /root/.ssh/id_rsa.pub stack@DESTINATION

2. The DESTINATION host's public ECDSA key (/etc/ssh/ssh_host_ecdsa_key.pub)
   needs to be in the SOURCE root user's known_hosts file
   (/root/.ssh/known_hosts). This can be accomplished by running the
   following on the SOURCE machine (hostname must be used)::

        ssh-keyscan -H DEST_HOSTNAME | sudo tee -a /root/.ssh/known_hosts

In essence, this means that every compute node's root user's public RSA key
must exist in every other compute node's stack user's authorized_keys file and
every compute node's public ECDSA key needs to be in every other compute
node's root user's known_hosts file.


Environment final checkup
-------------------------

If you are willing to make sure everything is in order in your DevStack
environment, you can run the Watcher Tempest tests which will validate its API
but also that you can perform the typical Watcher workflows. To do so, have a
look at the :ref:`Tempest tests <tempest_tests>` section which will explain to
you how to run them.
