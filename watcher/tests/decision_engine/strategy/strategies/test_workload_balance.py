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
import collections
import mock

from watcher.applier.loading import default
from watcher.common import exception
from watcher.common import utils
from watcher.decision_engine.model import element
from watcher.decision_engine.model import model_root
from watcher.decision_engine.strategy import strategies
from watcher.tests import base
from watcher.tests.decision_engine.strategy.strategies \
    import faker_cluster_state
from watcher.tests.decision_engine.strategy.strategies \
    import faker_metrics_collector


class TestWorkloadBalance(base.TestCase):

    def setUp(self):
        super(TestWorkloadBalance, self).setUp()
        # fake metrics
        self.fake_metrics = faker_metrics_collector.FakerMetricsCollector()
        # fake cluster
        self.fake_cluster = faker_cluster_state.FakerModelCollector()

        p_model = mock.patch.object(
            strategies.WorkloadBalance, "compute_model",
            new_callable=mock.PropertyMock)
        self.m_model = p_model.start()
        self.addCleanup(p_model.stop)

        p_ceilometer = mock.patch.object(
            strategies.WorkloadBalance, "ceilometer",
            new_callable=mock.PropertyMock)
        self.m_ceilometer = p_ceilometer.start()
        self.addCleanup(p_ceilometer.stop)

        self.m_model.return_value = model_root.ModelRoot()
        self.m_ceilometer.return_value = mock.Mock(
            statistic_aggregation=self.fake_metrics.mock_get_statistics_wb)
        self.strategy = strategies.WorkloadBalance(config=mock.Mock())
        self.strategy.input_parameters = utils.Struct()
        self.strategy.input_parameters.update({'threshold': 25.0,
                                               'period': 300})
        self.strategy.threshold = 25.0
        self.strategy._period = 300

    def test_calc_used_res(self):
        model = self.fake_cluster.generate_scenario_6_with_2_nodes()
        self.m_model.return_value = model
        node = model.get_node_by_uuid('Node_0')
        cap_cores = model.get_resource_by_uuid(element.ResourceType.cpu_cores)
        cap_mem = model.get_resource_by_uuid(element.ResourceType.memory)
        cap_disk = model.get_resource_by_uuid(element.ResourceType.disk)
        cores_used, mem_used, disk_used = (
            self.strategy.calculate_used_resource(
                node, cap_cores, cap_mem, cap_disk))

        self.assertEqual((cores_used, mem_used, disk_used), (20, 4, 40))

    def test_group_hosts_by_cpu_util(self):
        model = self.fake_cluster.generate_scenario_6_with_2_nodes()
        self.m_model.return_value = model
        self.strategy.threshold = 30
        n1, n2, avg, w_map = self.strategy.group_hosts_by_cpu_util()
        self.assertEqual(n1[0]['node'].uuid, 'Node_0')
        self.assertEqual(n2[0]['node'].uuid, 'Node_1')
        self.assertEqual(avg, 8.0)

    def test_choose_instance_to_migrate(self):
        model = self.fake_cluster.generate_scenario_6_with_2_nodes()
        self.m_model.return_value = model
        n1, n2, avg, w_map = self.strategy.group_hosts_by_cpu_util()
        instance_to_mig = self.strategy.choose_instance_to_migrate(
            n1, avg, w_map)
        self.assertEqual(instance_to_mig[0].uuid, 'Node_0')
        self.assertEqual(instance_to_mig[1].uuid,
                         "73b09e16-35b7-4922-804e-e8f5d9b740fc")

    def test_choose_instance_notfound(self):
        model = self.fake_cluster.generate_scenario_6_with_2_nodes()
        self.m_model.return_value = model
        n1, n2, avg, w_map = self.strategy.group_hosts_by_cpu_util()
        instances = model.get_all_instances()
        instances.clear()
        instance_to_mig = self.strategy.choose_instance_to_migrate(
            n1, avg, w_map)
        self.assertIsNone(instance_to_mig)

    def test_filter_destination_hosts(self):
        model = self.fake_cluster.generate_scenario_6_with_2_nodes()
        self.m_model.return_value = model
        self.strategy.ceilometer = mock.MagicMock(
            statistic_aggregation=self.fake_metrics.mock_get_statistics_wb)
        n1, n2, avg, w_map = self.strategy.group_hosts_by_cpu_util()
        instance_to_mig = self.strategy.choose_instance_to_migrate(
            n1, avg, w_map)
        dest_hosts = self.strategy.filter_destination_hosts(
            n2, instance_to_mig[1], avg, w_map)
        self.assertEqual(len(dest_hosts), 1)
        self.assertEqual(dest_hosts[0]['node'].uuid, 'Node_1')

    def test_exception_model(self):
        self.m_model.return_value = None
        self.assertRaises(
            exception.ClusterStateNotDefined, self.strategy.execute)

    def test_exception_cluster_empty(self):
        model = model_root.ModelRoot()
        self.m_model.return_value = model
        self.assertRaises(exception.ClusterEmpty, self.strategy.execute)

    def test_exception_stale_cdm(self):
        self.fake_cluster.set_cluster_data_model_as_stale()
        self.m_model.return_value = self.fake_cluster.cluster_data_model

        self.assertRaises(
            exception.ClusterStateNotDefined,
            self.strategy.execute)

    def test_execute_cluster_empty(self):
        model = model_root.ModelRoot()
        self.m_model.return_value = model
        self.assertRaises(exception.ClusterEmpty, self.strategy.execute)

    def test_execute_no_workload(self):
        model = self.fake_cluster.generate_scenario_4_with_1_node_no_instance()
        self.m_model.return_value = model
        solution = self.strategy.execute()
        self.assertEqual([], solution.actions)

    def test_execute(self):
        model = self.fake_cluster.generate_scenario_6_with_2_nodes()
        self.m_model.return_value = model
        solution = self.strategy.execute()
        actions_counter = collections.Counter(
            [action.get('action_type') for action in solution.actions])

        num_migrations = actions_counter.get("migrate", 0)
        self.assertEqual(num_migrations, 1)

    def test_check_parameters(self):
        model = self.fake_cluster.generate_scenario_6_with_2_nodes()
        self.m_model.return_value = model
        solution = self.strategy.execute()
        loader = default.DefaultActionLoader()
        for action in solution.actions:
            loaded_action = loader.load(action['action_type'])
            loaded_action.input_parameters = action['input_parameters']
            loaded_action.validate_parameters()
