# -*- encoding: utf-8 -*-
# Copyright (c) 2016 b<>com
#
# Authors: Vincent FRANCOISE <Vincent.FRANCOISE@b-com.com>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from oslo_log import log

from watcher._i18n import _LI
from watcher.common import exception
from watcher.common import nova_helper
from watcher.decision_engine.model import element
from watcher.decision_engine.model.notification import base
from watcher.decision_engine.model.notification import filtering

LOG = log.getLogger(__name__)


class NovaNotification(base.NotificationEndpoint):

    def __init__(self, collector):
        super(NovaNotification, self).__init__(collector)
        self._nova = None

    @property
    def nova(self):
        if self._nova is None:
            self._nova = nova_helper.NovaHelper()
        return self._nova

    def get_or_create_instance(self, uuid):
        try:
            instance = self.cluster_data_model.get_instance_by_uuid(uuid)
        except exception.InstanceNotFound:
            # The instance didn't exist yet so we create a new instance object
            LOG.debug("New instance created: %s", uuid)
            instance = element.Instance()
            instance.uuid = uuid

            self.cluster_data_model.add_instance(instance)

        return instance

    def update_instance(self, instance, data):
        instance_data = data['nova_object.data']
        instance_flavor_data = instance_data['flavor']['nova_object.data']

        instance.state = instance_data['state']
        instance.hostname = instance_data['host_name']
        instance.human_id = instance_data['display_name']

        memory_mb = instance_flavor_data['memory_mb']
        num_cores = instance_flavor_data['vcpus']
        disk_gb = instance_flavor_data['root_gb']

        self.update_capacity(element.ResourceType.memory, instance, memory_mb)
        self.update_capacity(
            element.ResourceType.cpu_cores, instance, num_cores)
        self.update_capacity(
            element.ResourceType.disk, instance, disk_gb)
        self.update_capacity(
            element.ResourceType.disk_capacity, instance, disk_gb)

        try:
            node = self.get_or_create_node(instance_data['host'])
        except exception.ComputeNodeNotFound as exc:
            LOG.exception(exc)
            # If we can't create the node, we consider the instance as unmapped
            node = None

        self.update_instance_mapping(instance, node)

    def update_capacity(self, resource_id, obj, value):
        resource = self.cluster_data_model.get_resource_by_uuid(resource_id)
        resource.set_capacity(obj, value)

    def legacy_update_instance(self, instance, data):
        instance.state = data['state']
        instance.hostname = data['hostname']
        instance.human_id = data['display_name']

        memory_mb = data['memory_mb']
        num_cores = data['vcpus']
        disk_gb = data['root_gb']

        self.update_capacity(element.ResourceType.memory, instance, memory_mb)
        self.update_capacity(
            element.ResourceType.cpu_cores, instance, num_cores)
        self.update_capacity(
            element.ResourceType.disk, instance, disk_gb)
        self.update_capacity(
            element.ResourceType.disk_capacity, instance, disk_gb)

        try:
            node = self.get_or_create_node(data['host'])
        except exception.ComputeNodeNotFound as exc:
            LOG.exception(exc)
            # If we can't create the node, we consider the instance as unmapped
            node = None

        self.update_instance_mapping(instance, node)

    def update_compute_node(self, node, data):
        """Update the compute node using the notification data."""
        node_data = data['nova_object.data']
        node.hostname = node_data['host']
        node.state = (
            element.ServiceState.OFFLINE.value
            if node_data['forced_down'] else element.ServiceState.ONLINE.value)
        node.status = (
            element.ServiceState.DISABLED.value
            if node_data['host'] else element.ServiceState.ENABLED.value)

    def create_compute_node(self, node_hostname):
        """Update the compute node by querying the Nova API."""
        try:
            _node = self.nova.get_compute_node_by_hostname(node_hostname)
            node = element.ComputeNode(_node.id)
            node.uuid = node_hostname
            node.hostname = _node.hypervisor_hostname
            node.state = _node.state
            node.status = _node.status

            self.update_capacity(
                element.ResourceType.memory, node, _node.memory_mb)
            self.update_capacity(
                element.ResourceType.cpu_cores, node, _node.vcpus)
            self.update_capacity(
                element.ResourceType.disk, node, _node.free_disk_gb)
            self.update_capacity(
                element.ResourceType.disk_capacity, node, _node.local_gb)
            return node
        except Exception as exc:
            LOG.exception(exc)
            LOG.debug("Could not refresh the node %s.", node_hostname)
            raise exception.ComputeNodeNotFound(name=node_hostname)

        return False

    def get_or_create_node(self, uuid):
        if uuid is None:
            LOG.debug("Compute node UUID not provided: skipping")
            return
        try:
            return self.cluster_data_model.get_node_by_uuid(uuid)
        except exception.ComputeNodeNotFound:
            # The node didn't exist yet so we create a new node object
            node = self.create_compute_node(uuid)
            LOG.debug("New compute node created: %s", uuid)
            self.cluster_data_model.add_node(node)
            return node

    def update_instance_mapping(self, instance, node):
        if node is None:
            self.cluster_data_model.add_instance(instance)
            LOG.debug("Instance %s not yet attached to any node: skipping",
                      instance.uuid)
            return
        try:
            try:
                old_node = self.get_or_create_node(node.uuid)
            except exception.ComputeNodeNotFound as exc:
                LOG.exception(exc)
                # If we can't create the node,
                # we consider the instance as unmapped
                old_node = None

            LOG.debug("Mapped node %s found", node.uuid)
            if node and node != old_node:
                LOG.debug("Unmapping instance %s from %s",
                          instance.uuid, node.uuid)
                self.cluster_data_model.unmap_instance(instance, old_node)
        except exception.InstanceNotFound:
            # The instance didn't exist yet so we map it for the first time
            LOG.debug("New instance: mapping it to %s", node.uuid)
        finally:
            if node:
                self.cluster_data_model.map_instance(instance, node)
                LOG.debug("Mapped instance %s to %s", instance.uuid, node.uuid)

    def delete_instance(self, instance, node):
        try:
            self.cluster_data_model.delete_instance(instance, node)
        except Exception:
            LOG.info(_LI("Instance %s already deleted"), instance.uuid)


class VersionnedNotificationEndpoint(NovaNotification):
    publisher_id_regex = r'^nova-compute.*'


class UnversionnedNotificationEndpoint(NovaNotification):
    publisher_id_regex = r'^compute.*'


class ServiceUpdated(VersionnedNotificationEndpoint):

    @property
    def filter_rule(self):
        """Nova service.update notification filter"""
        return filtering.NotificationFilter(
            publisher_id=self.publisher_id_regex,
            event_type='service.update',
        )

    def info(self, ctxt, publisher_id, event_type, payload, metadata):
        LOG.info(_LI("Event '%(event)s' received from %(publisher)s "
                     "with metadata %(metadata)s") %
                 dict(event=event_type,
                      publisher=publisher_id,
                      metadata=metadata))
        node_data = payload['nova_object.data']
        node_uuid = node_data['host']
        try:
            node = self.get_or_create_node(node_uuid)
            self.update_compute_node(node, payload)
        except exception.ComputeNodeNotFound as exc:
            LOG.exception(exc)


class InstanceCreated(VersionnedNotificationEndpoint):

    @property
    def filter_rule(self):
        """Nova instance.update notification filter"""
        return filtering.NotificationFilter(
            publisher_id=self.publisher_id_regex,
            event_type='instance.update',
            # To be "fully" created, an instance transitions
            # from the 'building' state to the 'active' one.
            # See http://docs.openstack.org/developer/nova/vmstates.html
            payload={
                'nova_object.data': {
                    'state': element.InstanceState.ACTIVE.value,
                    'state_update': {
                        'nova_object.data': {
                            'old_state': element.InstanceState.BUILDING.value,
                            'state': element.InstanceState.ACTIVE.value,
                        },
                        'nova_object.name': 'InstanceStateUpdatePayload',
                        'nova_object.namespace': 'nova',
                    },
                }
            }
        )

    def info(self, ctxt, publisher_id, event_type, payload, metadata):
        LOG.info(_LI("Event '%(event)s' received from %(publisher)s "
                     "with metadata %(metadata)s") %
                 dict(event=event_type,
                      publisher=publisher_id,
                      metadata=metadata))
        instance_data = payload['nova_object.data']

        instance_uuid = instance_data['uuid']
        instance = self.get_or_create_instance(instance_uuid)

        self.update_instance(instance, payload)


class InstanceUpdated(VersionnedNotificationEndpoint):

    @staticmethod
    def _match_not_new_instance_state(data):
        is_new_instance = (
            data['old_state'] == element.InstanceState.BUILDING.value and
            data['state'] == element.InstanceState.ACTIVE.value)

        return not is_new_instance

    @property
    def filter_rule(self):
        """Nova instance.update notification filter"""
        return filtering.NotificationFilter(
            publisher_id=self.publisher_id_regex,
            event_type='instance.update',
        )

    def info(self, ctxt, publisher_id, event_type, payload, metadata):
        LOG.info(_LI("Event '%(event)s' received from %(publisher)s "
                     "with metadata %(metadata)s") %
                 dict(event=event_type,
                      publisher=publisher_id,
                      metadata=metadata))
        instance_data = payload['nova_object.data']
        instance_uuid = instance_data['uuid']
        instance = self.get_or_create_instance(instance_uuid)

        self.update_instance(instance, payload)


class InstanceDeletedEnd(VersionnedNotificationEndpoint):

    @property
    def filter_rule(self):
        """Nova service.update notification filter"""
        return filtering.NotificationFilter(
            publisher_id=self.publisher_id_regex,
            event_type='instance.delete.end',
        )

    def info(self, ctxt, publisher_id, event_type, payload, metadata):
        LOG.info(_LI("Event '%(event)s' received from %(publisher)s "
                     "with metadata %(metadata)s") %
                 dict(event=event_type,
                      publisher=publisher_id,
                      metadata=metadata))

        instance_data = payload['nova_object.data']
        instance_uuid = instance_data['uuid']
        instance = self.get_or_create_instance(instance_uuid)

        try:
            node = self.get_or_create_node(instance_data['host'])
        except exception.ComputeNodeNotFound as exc:
            LOG.exception(exc)
            # If we can't create the node, we consider the instance as unmapped
            node = None

        self.delete_instance(instance, node)


class LegacyInstanceUpdated(UnversionnedNotificationEndpoint):

    @property
    def filter_rule(self):
        """Nova compute.instance.update notification filter"""
        return filtering.NotificationFilter(
            publisher_id=self.publisher_id_regex,
            event_type='compute.instance.update',
        )

    def info(self, ctxt, publisher_id, event_type, payload, metadata):
        LOG.info(_LI("Event '%(event)s' received from %(publisher)s "
                     "with metadata %(metadata)s") %
                 dict(event=event_type,
                      publisher=publisher_id,
                      metadata=metadata))

        instance_uuid = payload['instance_id']
        instance = self.get_or_create_instance(instance_uuid)

        self.legacy_update_instance(instance, payload)


class LegacyInstanceCreatedEnd(UnversionnedNotificationEndpoint):

    @property
    def filter_rule(self):
        """Nova compute.instance.create.end notification filter"""
        return filtering.NotificationFilter(
            publisher_id=self.publisher_id_regex,
            event_type='compute.instance.create.end',
        )

    def info(self, ctxt, publisher_id, event_type, payload, metadata):
        LOG.info(_LI("Event '%(event)s' received from %(publisher)s "
                     "with metadata %(metadata)s") %
                 dict(event=event_type,
                      publisher=publisher_id,
                      metadata=metadata))

        instance_uuid = payload['instance_id']
        instance = self.get_or_create_instance(instance_uuid)

        self.legacy_update_instance(instance, payload)


class LegacyInstanceDeletedEnd(UnversionnedNotificationEndpoint):

    @property
    def filter_rule(self):
        """Nova compute.instance.delete.end notification filter"""
        return filtering.NotificationFilter(
            publisher_id=self.publisher_id_regex,
            event_type='compute.instance.delete.end',
        )

    def info(self, ctxt, publisher_id, event_type, payload, metadata):
        LOG.info(_LI("Event '%(event)s' received from %(publisher)s "
                     "with metadata %(metadata)s") %
                 dict(event=event_type,
                      publisher=publisher_id,
                      metadata=metadata))
        instance_uuid = payload['instance_id']
        instance = self.get_or_create_instance(instance_uuid)

        try:
            node = self.get_or_create_node(payload['host'])
        except exception.ComputeNodeNotFound as exc:
            LOG.exception(exc)
            # If we can't create the node, we consider the instance as unmapped
            node = None

        self.delete_instance(instance, node)


class LegacyLiveMigratedEnd(UnversionnedNotificationEndpoint):

    @property
    def filter_rule(self):
        """Nova *.live_migration.post.dest.end notification filter"""
        return filtering.NotificationFilter(
            publisher_id=self.publisher_id_regex,
            event_type='compute.instance.live_migration.post.dest.end',
        )

    def info(self, ctxt, publisher_id, event_type, payload, metadata):
        LOG.info(_LI("Event '%(event)s' received from %(publisher)s "
                     "with metadata %(metadata)s") %
                 dict(event=event_type,
                      publisher=publisher_id,
                      metadata=metadata))

        instance_uuid = payload['instance_id']
        instance = self.get_or_create_instance(instance_uuid)

        self.legacy_update_instance(instance, payload)
