# -*- encoding: utf-8 -*-
# Copyright (c) 2015 Intel Corp
#
# Authors: Junjie-Huang <junjie.huang@intel.com>
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
#

"""
*Good Thermal Strategy*:

Towards to software defined infrastructure, the power and thermal
intelligences is being adopted to optimize workload, which can help
improve efficiency, reduce power, as well as to improve datacenter PUE
and lower down operation cost in data center.
Outlet (Exhaust Air) Temperature is one of the important thermal
telemetries to measure thermal/workload status of server.
"""

from oslo_log import log

from watcher._i18n import _, _LW, _LI
from watcher.common import exception as wexc
from watcher.decision_engine.cluster.history import ceilometer as ceil
from watcher.decision_engine.model import element
from watcher.decision_engine.strategy.strategies import base


LOG = log.getLogger(__name__)


class OutletTempControl(base.ThermalOptimizationBaseStrategy):
    """[PoC] Outlet temperature control using live migration

    *Description*

    It is a migration strategy based on the outlet temperature of compute
    hosts. It generates solutions to move a workload whenever a server's
    outlet temperature is higher than the specified threshold.

    *Requirements*

    * Hardware: All computer hosts should support IPMI and PTAS technology
    * Software: Ceilometer component ceilometer-agent-ipmi running
      in each compute host, and Ceilometer API can report such telemetry
      ``hardware.ipmi.node.outlet_temperature`` successfully.
    * You must have at least 2 physical compute hosts to run this strategy.

    *Limitations*

    - This is a proof of concept that is not meant to be used in production
    - We cannot forecast how many servers should be migrated. This is the
      reason why we only plan a single virtual machine migration at a time.
      So it's better to use this algorithm with `CONTINUOUS` audits.
    - It assume that live migrations are possible

    *Spec URL*

    https://github.com/openstack/watcher-specs/blob/master/specs/mitaka/approved/outlet-temperature-based-strategy.rst
    """  # noqa

    # The meter to report outlet temperature in ceilometer
    METER_NAME = "hardware.ipmi.node.outlet_temperature"
    MIGRATION = "migrate"

    def __init__(self, config, osc=None):
        """Outlet temperature control using live migration

        :param config: A mapping containing the configuration of this strategy
        :type config: dict
        :param osc: an OpenStackClients object, defaults to None
        :type osc: :py:class:`~.OpenStackClients` instance, optional
        """
        super(OutletTempControl, self).__init__(config, osc)
        self._meter = self.METER_NAME
        self._ceilometer = None

    @classmethod
    def get_name(cls):
        return "outlet_temperature"

    @classmethod
    def get_display_name(cls):
        return _("Outlet temperature based strategy")

    @classmethod
    def get_translatable_display_name(cls):
        return "Outlet temperature based strategy"

    @classmethod
    def get_schema(cls):
        # Mandatory default setting for each element
        return {
            "properties": {
                "threshold": {
                    "description": "temperature threshold for migration",
                    "type": "number",
                    "default": 35.0
                },
            },
        }

    @property
    def ceilometer(self):
        if self._ceilometer is None:
            self._ceilometer = ceil.CeilometerClusterHistory(osc=self.osc)
        return self._ceilometer

    @ceilometer.setter
    def ceilometer(self, c):
        self._ceilometer = c

    def calc_used_res(self, node, cpu_capacity,
                      memory_capacity, disk_capacity):
        """Calculate the used vcpus, memory and disk based on VM flavors"""
        instances = self.compute_model.mapping.get_node_instances(node)
        vcpus_used = 0
        memory_mb_used = 0
        disk_gb_used = 0
        if len(instances) > 0:
            for instance_id in instances:
                instance = self.compute_model.get_instance_by_uuid(instance_id)
                vcpus_used += cpu_capacity.get_capacity(instance)
                memory_mb_used += memory_capacity.get_capacity(instance)
                disk_gb_used += disk_capacity.get_capacity(instance)

        return vcpus_used, memory_mb_used, disk_gb_used

    def group_hosts_by_outlet_temp(self):
        """Group hosts based on outlet temp meters"""
        nodes = self.compute_model.get_all_compute_nodes()
        size_cluster = len(nodes)
        if size_cluster == 0:
            raise wexc.ClusterEmpty()

        hosts_need_release = []
        hosts_target = []
        for node_id in nodes:
            node = self.compute_model.get_node_by_uuid(
                node_id)
            resource_id = node.uuid

            outlet_temp = self.ceilometer.statistic_aggregation(
                resource_id=resource_id,
                meter_name=self._meter,
                period="30",
                aggregate='avg')
            # some hosts may not have outlet temp meters, remove from target
            if outlet_temp is None:
                LOG.warning(_LW("%s: no outlet temp data"), resource_id)
                continue

            LOG.debug("%s: outlet temperature %f" % (resource_id, outlet_temp))
            instance_data = {'node': node, 'outlet_temp': outlet_temp}
            if outlet_temp >= self.threshold:
                # mark the node to release resources
                hosts_need_release.append(instance_data)
            else:
                hosts_target.append(instance_data)
        return hosts_need_release, hosts_target

    def choose_instance_to_migrate(self, hosts):
        """Pick up an active instance to migrate from provided hosts"""
        for instance_data in hosts:
            mig_source_node = instance_data['node']
            instances_of_src = self.compute_model.mapping.get_node_instances(
                mig_source_node)
            if len(instances_of_src) > 0:
                for instance_id in instances_of_src:
                    try:
                        # select the first active instance to migrate
                        instance = self.compute_model.get_instance_by_uuid(
                            instance_id)
                        if (instance.state !=
                                element.InstanceState.ACTIVE.value):
                            LOG.info(_LI("Instance not active, skipped: %s"),
                                     instance.uuid)
                            continue
                        return mig_source_node, instance
                    except wexc.InstanceNotFound as e:
                        LOG.exception(e)
                        LOG.info(_LI("Instance not found"))

        return None

    def filter_dest_servers(self, hosts, instance_to_migrate):
        """Only return hosts with sufficient available resources"""
        cpu_capacity = self.compute_model.get_resource_by_uuid(
            element.ResourceType.cpu_cores)
        disk_capacity = self.compute_model.get_resource_by_uuid(
            element.ResourceType.disk)
        memory_capacity = self.compute_model.get_resource_by_uuid(
            element.ResourceType.memory)

        required_cores = cpu_capacity.get_capacity(instance_to_migrate)
        required_disk = disk_capacity.get_capacity(instance_to_migrate)
        required_memory = memory_capacity.get_capacity(instance_to_migrate)

        # filter nodes without enough resource
        dest_servers = []
        for instance_data in hosts:
            host = instance_data['node']
            # available
            cores_used, mem_used, disk_used = self.calc_used_res(
                host, cpu_capacity, memory_capacity, disk_capacity)
            cores_available = cpu_capacity.get_capacity(host) - cores_used
            disk_available = disk_capacity.get_capacity(host) - disk_used
            mem_available = memory_capacity.get_capacity(host) - mem_used
            if cores_available >= required_cores \
                    and disk_available >= required_disk \
                    and mem_available >= required_memory:
                dest_servers.append(instance_data)

        return dest_servers

    def pre_execute(self):
        LOG.debug("Initializing Outlet temperature strategy")

        if not self.compute_model:
            raise wexc.ClusterStateNotDefined()

        LOG.debug(self.compute_model.to_string())

    def do_execute(self):
        # the migration plan will be triggered when the outlet temperature
        # reaches threshold
        self.threshold = self.input_parameters.threshold
        LOG.debug("Initializing Outlet temperature strategy with threshold=%d",
                  self.threshold)
        hosts_need_release, hosts_target = self.group_hosts_by_outlet_temp()

        if len(hosts_need_release) == 0:
            # TODO(zhenzanz): return something right if there's no hot servers
            LOG.debug("No hosts require optimization")
            return self.solution

        if len(hosts_target) == 0:
            LOG.warning(_LW("No hosts under outlet temp threshold found"))
            return self.solution

        # choose the server with highest outlet t
        hosts_need_release = sorted(hosts_need_release,
                                    reverse=True,
                                    key=lambda x: (x["outlet_temp"]))

        instance_to_migrate = self.choose_instance_to_migrate(
            hosts_need_release)
        # calculate the instance's cpu cores,memory,disk needs
        if instance_to_migrate is None:
            return self.solution

        mig_source_node, instance_src = instance_to_migrate
        dest_servers = self.filter_dest_servers(hosts_target, instance_src)
        # sort the filtered result by outlet temp
        # pick up the lowest one as dest server
        if len(dest_servers) == 0:
            # TODO(zhenzanz): maybe to warn that there's no resource
            # for instance.
            LOG.info(_LI("No proper target host could be found"))
            return self.solution

        dest_servers = sorted(dest_servers, key=lambda x: (x["outlet_temp"]))
        # always use the host with lowerest outlet temperature
        mig_destination_node = dest_servers[0]['node']
        # generate solution to migrate the instance to the dest server,
        if self.compute_model.migrate_instance(
                instance_src, mig_source_node, mig_destination_node):
            parameters = {'migration_type': 'live',
                          'source_node': mig_source_node.uuid,
                          'destination_node': mig_destination_node.uuid}
            self.solution.add_action(action_type=self.MIGRATION,
                                     resource_id=instance_src.uuid,
                                     input_parameters=parameters)

    def post_execute(self):
        self.solution.model = self.compute_model
        # TODO(v-francoise): Add the indicators to the solution

        LOG.debug(self.compute_model.to_string())
