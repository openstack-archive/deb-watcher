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


class WorkloadBalance(base.WorkloadStabilizationBaseStrategy):
    """[PoC]Workload balance using live migration

    *Description*

        It is a migration strategy based on the VM workload of physical
        servers. It generates solutions to move a workload whenever a server's
        CPU utilization % is higher than the specified threshold.
        The VM to be moved should make the host close to average workload
        of all compute nodes.

    *Requirements*

        * Hardware: compute node should use the same physical CPUs
        * Software: Ceilometer component ceilometer-agent-compute running
          in each compute node, and Ceilometer API can report such telemetry
          "cpu_util" successfully.
        * You must have at least 2 physical compute nodes to run this strategy

    *Limitations*

       - This is a proof of concept that is not meant to be used in production
       - We cannot forecast how many servers should be migrated. This is the
         reason why we only plan a single virtual machine migration at a time.
         So it's better to use this algorithm with `CONTINUOUS` audits.
       - It assume that live migrations are possible
    """

    # The meter to report CPU utilization % of VM in ceilometer
    METER_NAME = "cpu_util"
    # Unit: %, value range is [0 , 100]

    MIGRATION = "migrate"

    def __init__(self, config, osc=None):
        """Workload balance using live migration

        :param config: A mapping containing the configuration of this strategy
        :type config: :py:class:`~.Struct` instance
        :param osc: :py:class:`~.OpenStackClients` instance
        """
        super(WorkloadBalance, self).__init__(config, osc)
        # the migration plan will be triggered when the CPU utlization %
        # reaches threshold
        self._meter = self.METER_NAME
        self._ceilometer = None

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
        return "workload_balance"

    @classmethod
    def get_display_name(cls):
        return _("Workload Balance Migration Strategy")

    @classmethod
    def get_translatable_display_name(cls):
        return "Workload Balance Migration Strategy"

    @classmethod
    def get_schema(cls):
        # Mandatory default setting for each element
        return {
            "properties": {
                "threshold": {
                    "description": "workload threshold for migration",
                    "type": "number",
                    "default": 25.0
                },
                "period": {
                    "description": "aggregate time period of ceilometer",
                    "type": "number",
                    "default": 300
                },
            },
        }

    def calculate_used_resource(self, node, cap_cores, cap_mem,
                                cap_disk):
        """Calculate the used vcpus, memory and disk based on VM flavors"""
        instances = self.compute_model.mapping.get_node_instances(node)
        vcpus_used = 0
        memory_mb_used = 0
        disk_gb_used = 0
        for instance_id in instances:
            instance = self.compute_model.get_instance_by_uuid(instance_id)
            vcpus_used += cap_cores.get_capacity(instance)
            memory_mb_used += cap_mem.get_capacity(instance)
            disk_gb_used += cap_disk.get_capacity(instance)

        return vcpus_used, memory_mb_used, disk_gb_used

    def choose_instance_to_migrate(self, hosts, avg_workload, workload_cache):
        """Pick up an active instance instance to migrate from provided hosts

        :param hosts: the array of dict which contains node object
        :param avg_workload: the average workload value of all nodes
        :param workload_cache: the map contains instance to workload mapping
        """
        for instance_data in hosts:
            source_node = instance_data['node']
            source_instances = self.compute_model.mapping.get_node_instances(
                source_node)
            if source_instances:
                delta_workload = instance_data['workload'] - avg_workload
                min_delta = 1000000
                instance_id = None
                for inst_id in source_instances:
                    try:
                        # select the first active VM to migrate
                        instance = self.compute_model.get_instance_by_uuid(
                            inst_id)
                        if (instance.state !=
                                element.InstanceState.ACTIVE.value):
                            LOG.debug("Instance not active, skipped: %s",
                                      instance.uuid)
                            continue
                        current_delta = (
                            delta_workload - workload_cache[inst_id])
                        if 0 <= current_delta < min_delta:
                            min_delta = current_delta
                            instance_id = inst_id
                    except wexc.InstanceNotFound:
                        LOG.error(_LE("Instance not found; error: %s"),
                                  instance_id)
                if instance_id:
                    return (source_node,
                            self.compute_model.get_instance_by_uuid(
                                instance_id))
            else:
                LOG.info(_LI("VM not found from node: %s"),
                         source_node.uuid)

    def filter_destination_hosts(self, hosts, instance_to_migrate,
                                 avg_workload, workload_cache):
        '''Only return hosts with sufficient available resources'''

        cap_cores = self.compute_model.get_resource_by_uuid(
            element.ResourceType.cpu_cores)
        cap_disk = self.compute_model.get_resource_by_uuid(
            element.ResourceType.disk)
        cap_mem = self.compute_model.get_resource_by_uuid(
            element.ResourceType.memory)

        required_cores = cap_cores.get_capacity(instance_to_migrate)
        required_disk = cap_disk.get_capacity(instance_to_migrate)
        required_mem = cap_mem.get_capacity(instance_to_migrate)

        # filter nodes without enough resource
        destination_hosts = []
        src_instance_workload = workload_cache[instance_to_migrate.uuid]
        for instance_data in hosts:
            host = instance_data['node']
            workload = instance_data['workload']
            # calculate the available resources
            cores_used, mem_used, disk_used = self.calculate_used_resource(
                host, cap_cores, cap_mem, cap_disk)
            cores_available = cap_cores.get_capacity(host) - cores_used
            disk_available = cap_disk.get_capacity(host) - disk_used
            mem_available = cap_mem.get_capacity(host) - mem_used
            if (
                    cores_available >= required_cores and
                    disk_available >= required_disk and
                    mem_available >= required_mem and
                    (src_instance_workload + workload) < self.threshold / 100 *
                    cap_cores.get_capacity(host)
            ):
                destination_hosts.append(instance_data)

        return destination_hosts

    def group_hosts_by_cpu_util(self):
        """Calculate the workloads of each node

        try to find out the nodes which have reached threshold
        and the nodes which are under threshold.
        and also calculate the average workload value of all nodes.
        and also generate the instance workload map.
        """

        nodes = self.compute_model.get_all_compute_nodes()
        cluster_size = len(nodes)
        if not nodes:
            raise wexc.ClusterEmpty()
        # get cpu cores capacity of nodes and instances
        cap_cores = self.compute_model.get_resource_by_uuid(
            element.ResourceType.cpu_cores)
        overload_hosts = []
        nonoverload_hosts = []
        # total workload of cluster
        # it's the total core numbers being utilized in a cluster.
        cluster_workload = 0.0
        # use workload_cache to store the workload of VMs for reuse purpose
        workload_cache = {}
        for node_id in nodes:
            node = self.compute_model.get_node_by_uuid(
                node_id)
            instances = self.compute_model.mapping.get_node_instances(node)
            node_workload = 0.0
            for instance_id in instances:
                instance = self.compute_model.get_instance_by_uuid(instance_id)
                try:
                    cpu_util = self.ceilometer.statistic_aggregation(
                        resource_id=instance_id,
                        meter_name=self._meter,
                        period=self._period,
                        aggregate='avg')
                except Exception as exc:
                    LOG.exception(exc)
                    LOG.error(_LE("Can not get cpu_util from Ceilometer"))
                    continue
                if cpu_util is None:
                    LOG.debug("Instance (%s): cpu_util is None", instance_id)
                    continue
                instance_cores = cap_cores.get_capacity(instance)
                workload_cache[instance_id] = cpu_util * instance_cores / 100
                node_workload += workload_cache[instance_id]
                LOG.debug("VM (%s): cpu_util %f", instance_id, cpu_util)
            node_cores = cap_cores.get_capacity(node)
            hy_cpu_util = node_workload / node_cores * 100

            cluster_workload += node_workload

            instance_data = {
                'node': node, "cpu_util": hy_cpu_util,
                'workload': node_workload}
            if hy_cpu_util >= self.threshold:
                # mark the node to release resources
                overload_hosts.append(instance_data)
            else:
                nonoverload_hosts.append(instance_data)

        avg_workload = cluster_workload / cluster_size

        return overload_hosts, nonoverload_hosts, avg_workload, workload_cache

    def pre_execute(self):
        """Pre-execution phase

        This can be used to fetch some pre-requisites or data.
        """
        LOG.info(_LI("Initializing Workload Balance Strategy"))

        if not self.compute_model:
            raise wexc.ClusterStateNotDefined()

        LOG.debug(self.compute_model.to_string())

    def do_execute(self):
        """Strategy execution phase

        This phase is where you should put the main logic of your strategy.
        """
        self.threshold = self.input_parameters.threshold
        self._period = self.input_parameters.period
        source_nodes, target_nodes, avg_workload, workload_cache = (
            self.group_hosts_by_cpu_util())

        if not source_nodes:
            LOG.debug("No hosts require optimization")
            return self.solution

        if not target_nodes:
            LOG.warning(_LW("No hosts current have CPU utilization under %s "
                            "percent, therefore there are no possible target "
                            "hosts for any migration"),
                        self.threshold)
            return self.solution

        # choose the server with largest cpu_util
        source_nodes = sorted(source_nodes,
                              reverse=True,
                              key=lambda x: (x[self.METER_NAME]))

        instance_to_migrate = self.choose_instance_to_migrate(
            source_nodes, avg_workload, workload_cache)
        if not instance_to_migrate:
            return self.solution
        source_node, instance_src = instance_to_migrate
        # find the hosts that have enough resource for the VM to be migrated
        destination_hosts = self.filter_destination_hosts(
            target_nodes, instance_src, avg_workload, workload_cache)
        # sort the filtered result by workload
        # pick up the lowest one as dest server
        if not destination_hosts:
            # for instance.
            LOG.warning(_LW("No proper target host could be found, it might "
                            "be because of there's no enough CPU/Memory/DISK"))
            return self.solution
        destination_hosts = sorted(destination_hosts,
                                   key=lambda x: (x["cpu_util"]))
        # always use the host with lowerest CPU utilization
        mig_destination_node = destination_hosts[0]['node']
        # generate solution to migrate the instance to the dest server,
        if self.compute_model.migrate_instance(
                instance_src, source_node, mig_destination_node):
            parameters = {'migration_type': 'live',
                          'source_node': source_node.uuid,
                          'destination_node': mig_destination_node.uuid}
            self.solution.add_action(action_type=self.MIGRATION,
                                     resource_id=instance_src.uuid,
                                     input_parameters=parameters)

    def post_execute(self):
        """Post-execution phase

        This can be used to compute the global efficacy
        """
        self.solution.model = self.compute_model

        LOG.debug(self.compute_model.to_string())
