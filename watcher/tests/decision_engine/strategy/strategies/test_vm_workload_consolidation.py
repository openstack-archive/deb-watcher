# -*- encoding: utf-8 -*-
#
# Authors: Vojtech CIMA <cima@zhaw.ch>
#          Bruno GRAZIOLI <gaea@zhaw.ch>
#          Sean MURPHY <murp@zhaw.ch>
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

import mock

from watcher.common import exception
from watcher.decision_engine.model import model_root
from watcher.decision_engine.strategy import strategies
from watcher.tests import base
from watcher.tests.decision_engine.strategy.strategies \
    import faker_cluster_and_metrics


class TestVMWorkloadConsolidation(base.TestCase):

    def setUp(self):
        super(TestVMWorkloadConsolidation, self).setUp()

        # fake cluster
        self.fake_cluster = faker_cluster_and_metrics.FakerModelCollector()

        p_model = mock.patch.object(
            strategies.VMWorkloadConsolidation, "compute_model",
            new_callable=mock.PropertyMock)
        self.m_model = p_model.start()
        self.addCleanup(p_model.stop)

        p_ceilometer = mock.patch.object(
            strategies.VMWorkloadConsolidation, "ceilometer",
            new_callable=mock.PropertyMock)
        self.m_ceilometer = p_ceilometer.start()
        self.addCleanup(p_ceilometer.stop)

        # fake metrics
        self.fake_metrics = faker_cluster_and_metrics.FakeCeilometerMetrics(
            self.m_model.return_value)

        self.m_model.return_value = model_root.ModelRoot()
        self.m_ceilometer.return_value = mock.Mock(
            statistic_aggregation=self.fake_metrics.mock_get_statistics)
        self.strategy = strategies.VMWorkloadConsolidation(config=mock.Mock())

    def test_exception_stale_cdm(self):
        self.fake_cluster.set_cluster_data_model_as_stale()
        self.m_model.return_value = self.fake_cluster.cluster_data_model

        self.assertRaises(
            exception.ClusterStateNotDefined,
            self.strategy.execute)

    def test_get_instance_utilization(self):
        model = self.fake_cluster.generate_scenario_1()
        self.m_model.return_value = model
        self.fake_metrics.model = model
        instance_0 = model.get_instance_by_uuid("INSTANCE_0")
        instance_util = dict(cpu=1.0, ram=1, disk=10)
        self.assertEqual(
            instance_util,
            self.strategy.get_instance_utilization(instance_0.uuid, model))

    def test_get_node_utilization(self):
        model = self.fake_cluster.generate_scenario_1()
        self.m_model.return_value = model
        self.fake_metrics.model = model
        node_0 = model.get_node_by_uuid("Node_0")
        node_util = dict(cpu=1.0, ram=1, disk=10)
        self.assertEqual(
            node_util,
            self.strategy.get_node_utilization(node_0, model))

    def test_get_node_capacity(self):
        model = self.fake_cluster.generate_scenario_1()
        self.m_model.return_value = model
        self.fake_metrics.model = model
        node_0 = model.get_node_by_uuid("Node_0")
        node_util = dict(cpu=40, ram=64, disk=250)
        self.assertEqual(node_util,
                         self.strategy.get_node_capacity(node_0, model))

    def test_get_relative_node_utilization(self):
        model = self.fake_cluster.generate_scenario_1()
        self.m_model.return_value = model
        self.fake_metrics.model = model
        node = model.get_node_by_uuid('Node_0')
        rhu = self.strategy.get_relative_node_utilization(
            node, model)
        expected_rhu = {'disk': 0.04, 'ram': 0.015625, 'cpu': 0.025}
        self.assertEqual(expected_rhu, rhu)

    def test_get_relative_cluster_utilization(self):
        model = self.fake_cluster.generate_scenario_1()
        self.m_model.return_value = model
        self.fake_metrics.model = model
        cru = self.strategy.get_relative_cluster_utilization(model)
        expected_cru = {'cpu': 0.05, 'disk': 0.05, 'ram': 0.0234375}
        self.assertEqual(expected_cru, cru)

    def test_add_migration(self):
        model = self.fake_cluster.generate_scenario_1()
        self.m_model.return_value = model
        self.fake_metrics.model = model
        n1 = model.get_node_by_uuid('Node_0')
        n2 = model.get_node_by_uuid('Node_1')
        instance_uuid = 'INSTANCE_0'
        self.strategy.add_migration(instance_uuid, n1, n2, model)
        self.assertEqual(1, len(self.strategy.solution.actions))
        expected = {'action_type': 'migrate',
                    'input_parameters': {'destination_node': n2.uuid,
                                         'source_node': n1.uuid,
                                         'migration_type': 'live',
                                         'resource_id': instance_uuid}}
        self.assertEqual(expected, self.strategy.solution.actions[0])

    def test_is_overloaded(self):
        model = self.fake_cluster.generate_scenario_1()
        self.m_model.return_value = model
        self.fake_metrics.model = model
        n1 = model.get_node_by_uuid('Node_0')
        cc = {'cpu': 1.0, 'ram': 1.0, 'disk': 1.0}
        res = self.strategy.is_overloaded(n1, model, cc)
        self.assertFalse(res)

        cc = {'cpu': 0.025, 'ram': 1.0, 'disk': 1.0}
        res = self.strategy.is_overloaded(n1, model, cc)
        self.assertFalse(res)

        cc = {'cpu': 0.024, 'ram': 1.0, 'disk': 1.0}
        res = self.strategy.is_overloaded(n1, model, cc)
        self.assertTrue(res)

    def test_instance_fits(self):
        model = self.fake_cluster.generate_scenario_1()
        self.m_model.return_value = model
        self.fake_metrics.model = model
        n = model.get_node_by_uuid('Node_1')
        instance_uuid = 'INSTANCE_0'
        cc = {'cpu': 1.0, 'ram': 1.0, 'disk': 1.0}
        res = self.strategy.instance_fits(instance_uuid, n, model, cc)
        self.assertTrue(res)

        cc = {'cpu': 0.025, 'ram': 1.0, 'disk': 1.0}
        res = self.strategy.instance_fits(instance_uuid, n, model, cc)
        self.assertFalse(res)

    def test_add_action_enable_compute_node(self):
        model = self.fake_cluster.generate_scenario_1()
        self.m_model.return_value = model
        self.fake_metrics.model = model
        n = model.get_node_by_uuid('Node_0')
        self.strategy.add_action_enable_compute_node(n)
        expected = [{'action_type': 'change_nova_service_state',
                     'input_parameters': {'state': 'enabled',
                                          'resource_id': 'Node_0'}}]
        self.assertEqual(expected, self.strategy.solution.actions)

    def test_add_action_disable_node(self):
        model = self.fake_cluster.generate_scenario_1()
        self.m_model.return_value = model
        self.fake_metrics.model = model
        n = model.get_node_by_uuid('Node_0')
        self.strategy.add_action_disable_node(n)
        expected = [{'action_type': 'change_nova_service_state',
                     'input_parameters': {'state': 'disabled',
                                          'resource_id': 'Node_0'}}]
        self.assertEqual(expected, self.strategy.solution.actions)

    def test_disable_unused_nodes(self):
        model = self.fake_cluster.generate_scenario_1()
        self.m_model.return_value = model
        self.fake_metrics.model = model
        n1 = model.get_node_by_uuid('Node_0')
        n2 = model.get_node_by_uuid('Node_1')
        instance_uuid = 'INSTANCE_0'
        self.strategy.disable_unused_nodes(model)
        self.assertEqual(0, len(self.strategy.solution.actions))

        # Migrate VM to free the node
        self.strategy.add_migration(instance_uuid, n1, n2, model)

        self.strategy.disable_unused_nodes(model)
        expected = {'action_type': 'change_nova_service_state',
                    'input_parameters': {'state': 'disabled',
                                         'resource_id': 'Node_0'}}
        self.assertEqual(2, len(self.strategy.solution.actions))
        self.assertEqual(expected, self.strategy.solution.actions[1])

    def test_offload_phase(self):
        model = self.fake_cluster.generate_scenario_1()
        self.m_model.return_value = model
        self.fake_metrics.model = model
        cc = {'cpu': 1.0, 'ram': 1.0, 'disk': 1.0}
        self.strategy.offload_phase(model, cc)
        expected = []
        self.assertEqual(expected, self.strategy.solution.actions)

    def test_consolidation_phase(self):
        model = self.fake_cluster.generate_scenario_1()
        self.m_model.return_value = model
        self.fake_metrics.model = model
        n1 = model.get_node_by_uuid('Node_0')
        n2 = model.get_node_by_uuid('Node_1')
        instance_uuid = 'INSTANCE_0'
        cc = {'cpu': 1.0, 'ram': 1.0, 'disk': 1.0}
        self.strategy.consolidation_phase(model, cc)
        expected = [{'action_type': 'migrate',
                     'input_parameters': {'destination_node': n2.uuid,
                                          'source_node': n1.uuid,
                                          'migration_type': 'live',
                                          'resource_id': instance_uuid}}]
        self.assertEqual(expected, self.strategy.solution.actions)

    def test_strategy(self):
        model = self.fake_cluster.generate_scenario_2()
        self.m_model.return_value = model
        self.fake_metrics.model = model
        n1 = model.get_node_by_uuid('Node_0')
        cc = {'cpu': 1.0, 'ram': 1.0, 'disk': 1.0}
        self.strategy.offload_phase(model, cc)
        self.strategy.consolidation_phase(model, cc)
        self.strategy.optimize_solution(model)
        n2 = self.strategy.solution.actions[0][
            'input_parameters']['destination_node']
        expected = [{'action_type': 'migrate',
                     'input_parameters': {'destination_node': n2,
                                          'source_node': n1.uuid,
                                          'migration_type': 'live',
                                          'resource_id': 'INSTANCE_3'}},
                    {'action_type': 'migrate',
                     'input_parameters': {'destination_node': n2,
                                          'source_node': n1.uuid,
                                          'migration_type': 'live',
                                          'resource_id': 'INSTANCE_1'}}]

        self.assertEqual(expected, self.strategy.solution.actions)

    def test_strategy2(self):
        model = self.fake_cluster.generate_scenario_3()
        self.m_model.return_value = model
        self.fake_metrics.model = model
        n1 = model.get_node_by_uuid('Node_0')
        n2 = model.get_node_by_uuid('Node_1')
        cc = {'cpu': 1.0, 'ram': 1.0, 'disk': 1.0}
        self.strategy.offload_phase(model, cc)
        expected = [{'action_type': 'migrate',
                     'input_parameters': {'destination_node': n2.uuid,
                                          'migration_type': 'live',
                                          'resource_id': 'INSTANCE_6',
                                          'source_node': n1.uuid}},
                    {'action_type': 'migrate',
                     'input_parameters': {'destination_node': n2.uuid,
                                          'migration_type': 'live',
                                          'resource_id': 'INSTANCE_7',
                                          'source_node': n1.uuid}},
                    {'action_type': 'migrate',
                     'input_parameters': {'destination_node': n2.uuid,
                                          'migration_type': 'live',
                                          'resource_id': 'INSTANCE_8',
                                          'source_node': n1.uuid}}]
        self.assertEqual(expected, self.strategy.solution.actions)
        self.strategy.consolidation_phase(model, cc)
        expected.append({'action_type': 'migrate',
                         'input_parameters': {'destination_node': n1.uuid,
                                              'migration_type': 'live',
                                              'resource_id': 'INSTANCE_7',
                                              'source_node': n2.uuid}})
        self.assertEqual(expected, self.strategy.solution.actions)
        self.strategy.optimize_solution(model)
        del expected[3]
        del expected[1]
        self.assertEqual(expected, self.strategy.solution.actions)
