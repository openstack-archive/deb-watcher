# -*- encoding: utf-8 -*-
# Copyright (c) 2016 Intel Corp
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
from oslo_log import log

from watcher._i18n import _, _LE, _LI, _LW
from watcher.common import exception as wexc
from watcher.decision_engine.cluster.history import ceilometer as ceil
from watcher.decision_engine.model import element
from watcher.decision_engine.strategy.strategies import base

LOG = log.getLogger(__name__)


class UniformAirflow(base.BaseStrategy):
    """[PoC]Uniform Airflow using live migration

    *Description*

        It is a migration strategy based on the airflow of physical
        servers. It generates solutions to move VM whenever a server's
        airflow is higher than the specified threshold.

    *Requirements*

        * Hardware: compute node with NodeManager 3.0 support
        * Software: Ceilometer component ceilometer-agent-compute running
          in each compute node, and Ceilometer API can report such telemetry
          "airflow, system power, inlet temperature" successfully.
        * You must have at least 2 physical compute nodes to run this strategy

    *Limitations*

       - This is a proof of concept that is not meant to be used in production.
       - We cannot forecast how many servers should be migrated. This is the
         reason why we only plan a single virtual machine migration at a time.
         So it's better to use this algorithm with `CONTINUOUS` audits.
       - It assumes that live migrations are possible.
    """

    # The meter to report Airflow of physical server in ceilometer
    METER_NAME_AIRFLOW = "hardware.ipmi.node.airflow"
    # The meter to report inlet temperature of physical server in ceilometer
    METER_NAME_INLET_T = "hardware.ipmi.node.temperature"
    # The meter to report system power of physical server in ceilometer
    METER_NAME_POWER = "hardware.ipmi.node.power"
    # choose 300 seconds as the default duration of meter aggregation
    PERIOD = 300

    MIGRATION = "migrate"

    def __init__(self, config, osc=None):
        """Using live migration

        :param config: A mapping containing the configuration of this strategy
        :type config: dict
        :param osc: an OpenStackClients object
        """
        super(UniformAirflow, self).__init__(config, osc)
        # The migration plan will be triggered when the airflow reaches
        # threshold
        self.meter_name_airflow = self.METER_NAME_AIRFLOW
        self.meter_name_inlet_t = self.METER_NAME_INLET_T
        self.meter_name_power = self.METER_NAME_POWER
        self._ceilometer = None
        self._period = self.PERIOD

    @property
    def ceilometer(self):
        if self._ceilometer is None:
            self._ceilometer = ceil.CeilometerClusterHistory(osc=self.osc)
        return self._ceilometer

    @ceilometer.setter
    def ceilometer(self, c):
        self._ceilometer = c

    @classmethod
    def get_name(cls):
        return "uniform_airflow"

    @classmethod
    def get_display_name(cls):
        return _("Uniform airflow migration strategy")

    @classmethod
    def get_translatable_display_name(cls):
        return "Uniform airflow migration strategy"

    @classmethod
    def get_goal_name(cls):
        return "airflow_optimization"

    @classmethod
    def get_schema(cls):
        # Mandatory default setting for each element
        return {
            "properties": {
                "threshold_airflow": {
                    "description": ("airflow threshold for migration, Unit is "
                                    "0.1CFM"),
                    "type": "number",
                    "default": 400.0
                },
                "threshold_inlet_t": {
                    "description": ("inlet temperature threshold for "
                                    "migration decision"),
                    "type": "number",
                    "default": 28.0
                },
                "threshold_power": {
                    "description": ("system power threshold for migration "
                                    "decision"),
                    "type": "number",
                    "default": 350.0
                },
                "period": {
                    "description": "aggregate time period of ceilometer",
                    "type": "number",
                    "default": 300
                },
            },
        }

    def calculate_used_resource(self, node, cap_cores, cap_mem, cap_disk):
        """Compute the used vcpus, memory and disk based on instance flavors"""
        instances = self.compute_model.mapping.get_node_instances(node)
        vcpus_used = 0
        memory_mb_used = 0
        disk_gb_used = 0
        for instance_id in instances:
            instance = self.compute_model.get_instance_by_uuid(
                instance_id)
            vcpus_used += cap_cores.get_capacity(instance)
            memory_mb_used += cap_mem.get_capacity(instance)
            disk_gb_used += cap_disk.get_capacity(instance)

        return vcpus_used, memory_mb_used, disk_gb_used

    def choose_instance_to_migrate(self, hosts):
        """Pick up an active instance instance to migrate from provided hosts

        :param hosts: the array of dict which contains node object
        """
        instances_tobe_migrate = []
        for nodemap in hosts:
            source_node = nodemap['node']
            source_instances = self.compute_model.mapping.get_node_instances(
                source_node)
            if source_instances:
                inlet_t = self.ceilometer.statistic_aggregation(
                    resource_id=source_node.uuid,
                    meter_name=self.meter_name_inlet_t,
                    period=self._period,
                    aggregate='avg')
                power = self.ceilometer.statistic_aggregation(
                    resource_id=source_node.uuid,
                    meter_name=self.meter_name_power,
                    period=self._period,
                    aggregate='avg')
                if (power < self.threshold_power and
                        inlet_t < self.threshold_inlet_t):
                    # hardware issue, migrate all instances from this node
                    for instance_id in source_instances:
                        try:
                            instance = (self.compute_model.
                                        get_instance_by_uuid(instance_id))
                            instances_tobe_migrate.append(instance)
                        except wexc.InstanceNotFound:
                            LOG.error(_LE("Instance not found; error: %s"),
                                      instance_id)
                    return source_node, instances_tobe_migrate
                else:
                    # migrate the first active instance
                    for instance_id in source_instances:
                        try:
                            instance = (self.compute_model.
                                        get_instance_by_uuid(instance_id))
                            if (instance.state !=
                                    element.InstanceState.ACTIVE.value):
                                LOG.info(
                                    _LI("Instance not active, skipped: %s"),
                                    instance.uuid)
                                continue
                            instances_tobe_migrate.append(instance)
                            return source_node, instances_tobe_migrate
                        except wexc.InstanceNotFound:
                            LOG.error(_LE("Instance not found; error: %s"),
                                      instance_id)
            else:
                LOG.info(_LI("Instance not found on node: %s"),
                         source_node.uuid)

    def filter_destination_hosts(self, hosts, instances_to_migrate):
        """Find instance and host with sufficient available resources"""

        cap_cores = self.compute_model.get_resource_by_uuid(
            element.ResourceType.cpu_cores)
        cap_disk = self.compute_model.get_resource_by_uuid(
            element.ResourceType.disk)
        cap_mem = self.compute_model.get_resource_by_uuid(
            element.ResourceType.memory)
        # large instance go first
        instances_to_migrate = sorted(
            instances_to_migrate, reverse=True,
            key=lambda x: (cap_cores.get_capacity(x)))
        # find hosts for instances
        destination_hosts = []
        for instance_to_migrate in instances_to_migrate:
            required_cores = cap_cores.get_capacity(instance_to_migrate)
            required_disk = cap_disk.get_capacity(instance_to_migrate)
            required_mem = cap_mem.get_capacity(instance_to_migrate)
            dest_migrate_info = {}
            for nodemap in hosts:
                host = nodemap['node']
                if 'cores_used' not in nodemap:
                    # calculate the available resources
                    nodemap['cores_used'], nodemap['mem_used'],\
                        nodemap['disk_used'] = self.calculate_used_resource(
                            host, cap_cores, cap_mem, cap_disk)
                cores_available = (cap_cores.get_capacity(host) -
                                   nodemap['cores_used'])
                disk_available = (cap_disk.get_capacity(host) -
                                  nodemap['disk_used'])
                mem_available = (
                    cap_mem.get_capacity(host) - nodemap['mem_used'])
                if (cores_available >= required_cores and
                        disk_available >= required_disk and
                        mem_available >= required_mem):
                    dest_migrate_info['instance'] = instance_to_migrate
                    dest_migrate_info['node'] = host
                    nodemap['cores_used'] += required_cores
                    nodemap['mem_used'] += required_mem
                    nodemap['disk_used'] += required_disk
                    destination_hosts.append(dest_migrate_info)
                    break
        # check if all instances have target hosts
        if len(destination_hosts) != len(instances_to_migrate):
            LOG.warning(_LW("Not all target hosts could be found; it might "
                            "be because there is not enough resource"))
            return None
        return destination_hosts

    def group_hosts_by_airflow(self):
        """Group hosts based on airflow meters"""

        nodes = self.compute_model.get_all_compute_nodes()
        if not nodes:
            raise wexc.ClusterEmpty()
        overload_hosts = []
        nonoverload_hosts = []
        for node_id in nodes:
            node = self.compute_model.get_node_by_uuid(
                node_id)
            resource_id = node.uuid
            airflow = self.ceilometer.statistic_aggregation(
                resource_id=resource_id,
                meter_name=self.meter_name_airflow,
                period=self._period,
                aggregate='avg')
            # some hosts may not have airflow meter, remove from target
            if airflow is None:
                LOG.warning(_LW("%s: no airflow data"), resource_id)
                continue

            LOG.debug("%s: airflow %f" % (resource_id, airflow))
            nodemap = {'node': node, 'airflow': airflow}
            if airflow >= self.threshold_airflow:
                # mark the node to release resources
                overload_hosts.append(nodemap)
            else:
                nonoverload_hosts.append(nodemap)
        return overload_hosts, nonoverload_hosts

    def pre_execute(self):
        LOG.debug("Initializing Uniform Airflow Strategy")

        if not self.compute_model:
            raise wexc.ClusterStateNotDefined()

        LOG.debug(self.compute_model.to_string())

    def do_execute(self):
        self.threshold_airflow = self.input_parameters.threshold_airflow
        self.threshold_inlet_t = self.input_parameters.threshold_inlet_t
        self.threshold_power = self.input_parameters.threshold_power
        self._period = self.input_parameters.period
        source_nodes, target_nodes = self.group_hosts_by_airflow()

        if not source_nodes:
            LOG.debug("No hosts require optimization")
            return self.solution

        if not target_nodes:
            LOG.warning(_LW("No hosts currently have airflow under %s, "
                            "therefore there are no possible target "
                            "hosts for any migration"),
                        self.threshold_airflow)
            return self.solution

        # migrate the instance from server with largest airflow first
        source_nodes = sorted(source_nodes,
                              reverse=True,
                              key=lambda x: (x["airflow"]))
        instances_to_migrate = self.choose_instance_to_migrate(source_nodes)
        if not instances_to_migrate:
            return self.solution
        source_node, instances_src = instances_to_migrate
        # sort host with airflow
        target_nodes = sorted(target_nodes, key=lambda x: (x["airflow"]))
        # find the hosts that have enough resource
        # for the instance to be migrated
        destination_hosts = self.filter_destination_hosts(
            target_nodes, instances_src)
        if not destination_hosts:
            LOG.warning(_LW("No target host could be found; it might "
                            "be because there is not enough resources"))
            return self.solution
        # generate solution to migrate the instance to the dest server,
        for info in destination_hosts:
            instance = info['instance']
            destination_node = info['node']
            if self.compute_model.migrate_instance(
                    instance, source_node, destination_node):
                parameters = {'migration_type': 'live',
                              'source_node': source_node.uuid,
                              'destination_node': destination_node.uuid}
                self.solution.add_action(action_type=self.MIGRATION,
                                         resource_id=instance.uuid,
                                         input_parameters=parameters)

    def post_execute(self):
        self.solution.model = self.compute_model
        # TODO(v-francoise): Add the indicators to the solution

        LOG.debug(self.compute_model.to_string())
