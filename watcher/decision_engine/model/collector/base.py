# -*- encoding: utf-8 -*-
# Copyright (c) 2015 b<>com
#
# Authors: Jean-Emile DARTOIS <jean-emile.dartois@b-com.com>
#          Vincent FRANCOISE <vincent.francoise@b-com.com>
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
A :ref:`Cluster Data Model <cluster_data_model_definition>` is a logical
representation of the current state and topology of the :ref:`Cluster
<cluster_definition>` :ref:`Managed resources <managed_resource_definition>`.

It is represented as a set of :ref:`Managed resources
<managed_resource_definition>` (which may be a simple tree or a flat list of
key-value pairs) which enables Watcher :ref:`Strategies <strategy_definition>`
to know the current relationships between the different :ref:`resources
<managed_resource_definition>`) of the :ref:`Cluster <cluster_definition>`
during an :ref:`Audit <audit_definition>` and enables the :ref:`Strategy
<strategy_definition>` to request information such as:

- What compute nodes are in a given :ref:`Availability Zone
  <availability_zone_definition>` or a given :ref:`Host Aggregate
  <host_aggregates_definition>`?
- What :ref:`Instances <instance_definition>` are hosted on a given compute
  node?
- What is the current load of a compute node?
- What is the current free memory of a compute node?
- What is the network link between two compute nodes?
- What is the available bandwidth on a given network link?
- What is the current space available on a given virtual disk of a given
  :ref:`Instance <instance_definition>` ?
- What is the current state of a given :ref:`Instance <instance_definition>`?
- ...

In a word, this data model enables the :ref:`Strategy <strategy_definition>`
to know:

- the current topology of the :ref:`Cluster <cluster_definition>`
- the current capacity for each :ref:`Managed resource
  <managed_resource_definition>`
- the current amount of used/free space for each :ref:`Managed resource
  <managed_resource_definition>`
- the current state of each :ref:`Managed resources
  <managed_resource_definition>`

In the Watcher project, we aim at providing a some generic and basic
:ref:`Cluster Data Model <cluster_data_model_definition>` for each :ref:`Goal
<goal_definition>`, usable in the associated :ref:`Strategies
<strategy_definition>` through a plugin-based mechanism that are directly
accessible from the strategies classes in order to:

- simplify the development of a new :ref:`Strategy <strategy_definition>` for a
  given :ref:`Goal <goal_definition>` when there already are some existing
  :ref:`Strategies <strategy_definition>` associated to the same :ref:`Goal
  <goal_definition>`
- avoid duplicating the same code in several :ref:`Strategies
  <strategy_definition>` associated to the same :ref:`Goal <goal_definition>`
- have a better consistency between the different :ref:`Strategies
  <strategy_definition>` for a given :ref:`Goal <goal_definition>`
- avoid any strong coupling with any external :ref:`Cluster Data Model
  <cluster_data_model_definition>` (the proposed data model acts as a pivot
  data model)

There may be various :ref:`generic and basic Cluster Data Models
<cluster_data_model_definition>` proposed in Watcher helpers, each of them
being adapted to achieving a given :ref:`Goal <goal_definition>`:

- For example, for a :ref:`Goal <goal_definition>` which aims at optimizing
  the network :ref:`resources <managed_resource_definition>` the :ref:`Strategy
  <strategy_definition>` may need to know which :ref:`resources
  <managed_resource_definition>` are communicating together.
- Whereas for a :ref:`Goal <goal_definition>` which aims at optimizing thermal
  and power conditions, the :ref:`Strategy <strategy_definition>` may need to
  know the location of each compute node in the racks and the location of each
  rack in the room.

Note however that a developer can use his/her own :ref:`Cluster Data Model
<cluster_data_model_definition>` if the proposed data model does not fit
his/her needs as long as the :ref:`Strategy <strategy_definition>` is able to
produce a :ref:`Solution <solution_definition>` for the requested :ref:`Goal
<goal_definition>`. For example, a developer could rely on the Nova Data Model
to optimize some compute resources.

The :ref:`Cluster Data Model <cluster_data_model_definition>` may be persisted
in any appropriate storage system (SQL database, NoSQL database, JSON file,
XML File, In Memory Database, ...). As of now, an in-memory model is built and
maintained in the background in order to accelerate the execution of
strategies.
"""

import abc
import copy
import threading

from oslo_config import cfg
import six

from watcher.common import clients
from watcher.common.loader import loadable
from watcher.decision_engine.model import model_root


@six.add_metaclass(abc.ABCMeta)
class BaseClusterDataModelCollector(loadable.LoadableSingleton):

    STALE_MODEL = model_root.ModelRoot(stale=True)

    def __init__(self, config, osc=None):
        super(BaseClusterDataModelCollector, self).__init__(config)
        self.osc = osc if osc else clients.OpenStackClients()
        self._cluster_data_model = None
        self.lock = threading.RLock()

    @property
    def cluster_data_model(self):
        if self._cluster_data_model is None:
            self.lock.acquire()
            self._cluster_data_model = self.execute()
            self.lock.release()

        return self._cluster_data_model

    @cluster_data_model.setter
    def cluster_data_model(self, model):
        self.lock.acquire()
        self._cluster_data_model = model
        self.lock.release()

    @abc.abstractproperty
    def notification_endpoints(self):
        """Associated notification endpoints

        :return: Associated notification endpoints
        :rtype: List of :py:class:`~.EventsNotificationEndpoint` instances
        """
        raise NotImplementedError()

    def set_cluster_data_model_as_stale(self):
        self.cluster_data_model = self.STALE_MODEL

    @abc.abstractmethod
    def execute(self):
        """Build a cluster data model"""
        raise NotImplementedError()

    @classmethod
    def get_config_opts(cls):
        return [
            cfg.IntOpt(
                'period',
                default=3600,
                help='The time interval (in seconds) between each '
                     'synchronization of the model'),
        ]

    def get_latest_cluster_data_model(self):
        return copy.deepcopy(self.cluster_data_model)

    def synchronize(self):
        """Synchronize the cluster data model

        Whenever called this synchronization will perform a drop-in replacement
        with the existing cluster data model
        """
        self.cluster_data_model = self.execute()
