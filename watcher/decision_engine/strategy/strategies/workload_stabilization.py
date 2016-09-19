# -*- encoding: utf-8 -*-
# Copyright (c) 2016 Servionica LLC
#
# Authors: Alexander Chadin <a.chadin@servionica.ru>
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

import copy
import itertools
import math
import random

import oslo_cache
from oslo_config import cfg
from oslo_log import log

from watcher._i18n import _LI, _
from watcher.common import exception
from watcher.decision_engine.cluster.history import ceilometer as \
    ceilometer_cluster_history
from watcher.decision_engine.model import element
from watcher.decision_engine.strategy.strategies import base

LOG = log.getLogger(__name__)
CONF = cfg.CONF


def _set_memoize(conf):
    oslo_cache.configure(conf)
    region = oslo_cache.create_region()
    configured_region = oslo_cache.configure_cache_region(conf, region)
    return oslo_cache.core.get_memoization_decorator(conf,
                                                     configured_region,
                                                     'cache')


class WorkloadStabilization(base.WorkloadStabilizationBaseStrategy):
    """Workload Stabilization control using live migration

    *Description*

    This is workload stabilization strategy based on standard deviation
    algorithm. The goal is to determine if there is an overload in a cluster
    and respond to it by migrating VMs to stabilize the cluster.

    *Requirements*

    * Software: Ceilometer component ceilometer-compute running
      in each compute host, and Ceilometer API can report such telemetries
      ``memory.resident`` and ``cpu_util`` successfully.
    * You must have at least 2 physical compute nodes to run this strategy.

    *Limitations*

    - It assume that live migrations are possible
    - Load on the system is sufficiently stable.

    *Spec URL*

    https://review.openstack.org/#/c/286153/
    """

    MIGRATION = "migrate"
    MEMOIZE = _set_memoize(CONF)

    def __init__(self, config, osc=None):
        super(WorkloadStabilization, self).__init__(config, osc)
        self._ceilometer = None
        self._nova = None
        self.weights = None
        self.metrics = None
        self.thresholds = None
        self.host_choice = None
        self.instance_metrics = None
        self.retry_count = None

    @classmethod
    def get_name(cls):
        return "workload_stabilization"

    @classmethod
    def get_display_name(cls):
        return _("Workload stabilization")

    @classmethod
    def get_translatable_display_name(cls):
        return "Workload stabilization"

    @classmethod
    def get_schema(cls):
        return {
            "properties": {
                "metrics": {
                    "description": "Metrics used as rates of cluster loads.",
                    "type": "array",
                    "default": ["cpu_util", "memory.resident"]
                },
                "thresholds": {
                    "description": "Dict where key is a metric and value "
                                   "is a trigger value.",
                    "type": "object",
                    "default": {"cpu_util": 0.2, "memory.resident": 0.2}
                },
                "weights": {
                    "description": "These weights used to calculate "
                                   "common standard deviation. Name of weight"
                                   " contains meter name and _weight suffix.",
                    "type": "object",
                    "default": {"cpu_util_weight": 1.0,
                                "memory.resident_weight": 1.0}
                },
                "instance_metrics": {
                    "description": "Mapping to get hardware statistics using"
                                   " instance metrics",
                    "type": "object",
                    "default": {"cpu_util": "hardware.cpu.util",
                                "memory.resident": "hardware.memory.used"}
                },
                "host_choice": {
                    "description": "Method of host's choice. There are cycle,"
                                   " retry and fullsearch methods. "
                                   "Cycle will iterate hosts in cycle. "
                                   "Retry will get some hosts random "
                                   "(count defined in retry_count option). "
                                   "Fullsearch will return each host "
                                   "from list.",
                    "type": "string",
                    "default": "retry"
                },
                "retry_count": {
                    "description": "Count of random returned hosts",
                    "type": "number",
                    "default": 1
                }
            }
        }

    @property
    def ceilometer(self):
        if self._ceilometer is None:
            self._ceilometer = (ceilometer_cluster_history.
                                CeilometerClusterHistory(osc=self.osc))
        return self._ceilometer

    @property
    def nova(self):
        if self._nova is None:
            self._nova = self.osc.nova()
        return self._nova

    @nova.setter
    def nova(self, n):
        self._nova = n

    @ceilometer.setter
    def ceilometer(self, c):
        self._ceilometer = c

    def transform_instance_cpu(self, instance_load, host_vcpus):
        """Transform instance cpu utilization to overall host cpu utilization.

        :param instance_load: dict that contains instance uuid and
            utilization info.
        :param host_vcpus: int
        :return: float value
        """
        return (instance_load['cpu_util'] *
                (instance_load['vcpus'] / float(host_vcpus)))

    @MEMOIZE
    def get_instance_load(self, instance_uuid):
        """Gathering instance load through ceilometer statistic.

        :param instance_uuid: instance for which statistic is gathered.
        :return: dict
        """
        LOG.debug('get_instance_load started')
        instance_vcpus = self.compute_model.get_resource_by_uuid(
            element.ResourceType.cpu_cores).get_capacity(
                self.compute_model.get_instance_by_uuid(instance_uuid))
        instance_load = {'uuid': instance_uuid, 'vcpus': instance_vcpus}
        for meter in self.metrics:
            avg_meter = self.ceilometer.statistic_aggregation(
                resource_id=instance_uuid,
                meter_name=meter,
                period="120",
                aggregate='min'
            )
            if avg_meter is None:
                raise exception.NoMetricValuesForInstance(
                    resource_id=instance_uuid, metric_name=meter)
            instance_load[meter] = avg_meter
        return instance_load

    def normalize_hosts_load(self, hosts):
        normalized_hosts = copy.deepcopy(hosts)
        for host in normalized_hosts:
            if 'memory.resident' in normalized_hosts[host]:
                h_memory = self.compute_model.get_resource_by_uuid(
                    element.ResourceType.memory).get_capacity(
                        self.compute_model.get_node_by_uuid(host))
                normalized_hosts[host]['memory.resident'] /= float(h_memory)

        return normalized_hosts

    def get_hosts_load(self):
        """Get load of every host by gathering instances load"""
        hosts_load = {}
        for node_id in self.compute_model.get_all_compute_nodes():
            hosts_load[node_id] = {}
            host_vcpus = self.compute_model.get_resource_by_uuid(
                element.ResourceType.cpu_cores).get_capacity(
                    self.compute_model.get_node_by_uuid(node_id))
            hosts_load[node_id]['vcpus'] = host_vcpus

            for metric in self.metrics:
                avg_meter = self.ceilometer.statistic_aggregation(
                    resource_id=node_id,
                    meter_name=self.instance_metrics[metric],
                    period="60",
                    aggregate='avg'
                )
                if avg_meter is None:
                    raise exception.NoSuchMetricForHost(
                        metric=self.instance_metrics[metric],
                        host=node_id)
                hosts_load[node_id][metric] = avg_meter
        return hosts_load

    def get_sd(self, hosts, meter_name):
        """Get standard deviation among hosts by specified meter"""
        mean = 0
        variaton = 0
        for host_id in hosts:
            mean += hosts[host_id][meter_name]
        mean /= len(hosts)
        for host_id in hosts:
            variaton += (hosts[host_id][meter_name] - mean) ** 2
        variaton /= len(hosts)
        sd = math.sqrt(variaton)
        return sd

    def calculate_weighted_sd(self, sd_case):
        """Calculate common standard deviation among meters on host"""
        weighted_sd = 0
        for metric, value in zip(self.metrics, sd_case):
            try:
                weighted_sd += value * float(self.weights[metric + '_weight'])
            except KeyError as exc:
                LOG.exception(exc)
                raise exception.WatcherException(
                    _("Incorrect mapping: could not find associated weight"
                      " for %s in weight dict.") % metric)
        return weighted_sd

    def calculate_migration_case(self, hosts, instance_id,
                                 src_node_id, dst_node_id):
        """Calculate migration case

        Return list of standard deviation values, that appearing in case of
        migration of instance from source host to destination host
        :param hosts: hosts with their workload
        :param instance_id: the virtual machine
        :param src_node_id: the source node id
        :param dst_node_id: the destination node id
        :return: list of standard deviation values
        """
        migration_case = []
        new_hosts = copy.deepcopy(hosts)
        instance_load = self.get_instance_load(instance_id)
        d_host_vcpus = new_hosts[dst_node_id]['vcpus']
        s_host_vcpus = new_hosts[src_node_id]['vcpus']
        for metric in self.metrics:
            if metric is 'cpu_util':
                new_hosts[src_node_id][metric] -= self.transform_instance_cpu(
                    instance_load,
                    s_host_vcpus)
                new_hosts[dst_node_id][metric] += self.transform_instance_cpu(
                    instance_load,
                    d_host_vcpus)
            else:
                new_hosts[src_node_id][metric] -= instance_load[metric]
                new_hosts[dst_node_id][metric] += instance_load[metric]
        normalized_hosts = self.normalize_hosts_load(new_hosts)
        for metric in self.metrics:
            migration_case.append(self.get_sd(normalized_hosts, metric))
        migration_case.append(new_hosts)
        return migration_case

    def simulate_migrations(self, hosts):
        """Make sorted list of pairs instance:dst_host"""
        def yield_nodes(nodes):
            if self.host_choice == 'cycle':
                for i in itertools.cycle(nodes):
                    yield [i]
            if self.host_choice == 'retry':
                while True:
                    yield random.sample(nodes, self.retry_count)
            if self.host_choice == 'fullsearch':
                while True:
                    yield nodes

        instance_host_map = []
        nodes = list(self.compute_model.get_all_compute_nodes())
        for source_hp_id in nodes:
            c_nodes = copy.copy(nodes)
            c_nodes.remove(source_hp_id)
            node_list = yield_nodes(c_nodes)
            instances_id = self.compute_model.get_mapping(). \
                get_node_instances_by_uuid(source_hp_id)
            for instance_id in instances_id:
                min_sd_case = {'value': len(self.metrics)}
                instance = self.compute_model.get_instance_by_uuid(instance_id)
                if instance.state not in [element.InstanceState.ACTIVE.value,
                                          element.InstanceState.PAUSED.value]:
                    continue
                for dst_node_id in next(node_list):
                    sd_case = self.calculate_migration_case(hosts, instance_id,
                                                            source_hp_id,
                                                            dst_node_id)

                    weighted_sd = self.calculate_weighted_sd(sd_case[:-1])

                    if weighted_sd < min_sd_case['value']:
                        min_sd_case = {
                            'host': dst_node_id, 'value': weighted_sd,
                            's_host': source_hp_id, 'instance': instance_id}
                        instance_host_map.append(min_sd_case)
        return sorted(instance_host_map, key=lambda x: x['value'])

    def check_threshold(self):
        """Check if cluster is needed in balancing"""
        hosts_load = self.get_hosts_load()
        normalized_load = self.normalize_hosts_load(hosts_load)
        for metric in self.metrics:
            metric_sd = self.get_sd(normalized_load, metric)
            if metric_sd > float(self.thresholds[metric]):
                return self.simulate_migrations(hosts_load)

    def add_migration(self,
                      resource_id,
                      migration_type,
                      source_node,
                      destination_node):
        parameters = {'migration_type': migration_type,
                      'source_node': source_node,
                      'destination_node': destination_node}
        self.solution.add_action(action_type=self.MIGRATION,
                                 resource_id=resource_id,
                                 input_parameters=parameters)

    def create_migration_instance(self, mig_instance, mig_source_node,
                                  mig_destination_node):
        """Create migration VM"""
        if self.compute_model.migrate_instance(
                mig_instance, mig_source_node, mig_destination_node):
            self.add_migration(mig_instance.uuid, 'live',
                               mig_source_node.uuid,
                               mig_destination_node.uuid)

    def migrate(self, instance_uuid, src_host, dst_host):
        mig_instance = self.compute_model.get_instance_by_uuid(instance_uuid)
        mig_source_node = self.compute_model.get_node_by_uuid(
            src_host)
        mig_destination_node = self.compute_model.get_node_by_uuid(
            dst_host)
        self.create_migration_instance(mig_instance, mig_source_node,
                                       mig_destination_node)

    def fill_solution(self):
        self.solution.model = self.compute_model
        return self.solution

    def pre_execute(self):
        LOG.info(_LI("Initializing Workload Stabilization"))

        if not self.compute_model:
            raise exception.ClusterStateNotDefined()

        self.weights = self.input_parameters.weights
        self.metrics = self.input_parameters.metrics
        self.thresholds = self.input_parameters.thresholds
        self.host_choice = self.input_parameters.host_choice
        self.instance_metrics = self.input_parameters.instance_metrics
        self.retry_count = self.input_parameters.retry_count

    def do_execute(self):
        migration = self.check_threshold()
        if migration:
            hosts_load = self.get_hosts_load()
            min_sd = 1
            balanced = False
            for instance_host in migration:
                dst_hp_disk = self.compute_model.get_resource_by_uuid(
                    element.ResourceType.disk).get_capacity(
                        self.compute_model.get_node_by_uuid(
                            instance_host['host']))
                instance_disk = self.compute_model.get_resource_by_uuid(
                    element.ResourceType.disk).get_capacity(
                        self.compute_model.get_instance_by_uuid(
                            instance_host['instance']))
                if instance_disk > dst_hp_disk:
                    continue
                instance_load = self.calculate_migration_case(
                    hosts_load, instance_host['instance'],
                    instance_host['s_host'], instance_host['host'])
                weighted_sd = self.calculate_weighted_sd(instance_load[:-1])
                if weighted_sd < min_sd:
                    min_sd = weighted_sd
                    hosts_load = instance_load[-1]
                    self.migrate(instance_host['instance'],
                                 instance_host['s_host'],
                                 instance_host['host'])

                for metric, value in zip(self.metrics, instance_load[:-1]):
                    if value < float(self.thresholds[metric]):
                        balanced = True
                        break
                if balanced:
                    break

    def post_execute(self):
        """Post-execution phase

        This can be used to compute the global efficacy
        """
        self.fill_solution()

        LOG.debug(self.compute_model.to_string())
