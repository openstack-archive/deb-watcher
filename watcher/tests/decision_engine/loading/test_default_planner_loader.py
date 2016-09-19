# -*- encoding: utf-8 -*-
# Copyright (c) 2016 b<>com
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

from watcher.decision_engine.loading import default
from watcher.decision_engine.planner import base as planner
from watcher.tests import base


class TestDefaultPlannerLoader(base.TestCase):
    def setUp(self):
        super(TestDefaultPlannerLoader, self).setUp()
        self.loader = default.DefaultPlannerLoader()

    def test_endpoints(self):
        for endpoint in self.loader.list_available():
            loaded = self.loader.load(endpoint)
            self.assertIsNotNone(loaded)
            self.assertIsInstance(loaded, planner.BasePlanner)
