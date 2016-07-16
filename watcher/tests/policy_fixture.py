# Copyright 2012 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import os

import fixtures
from oslo_config import cfg
from oslo_policy import _parser
from oslo_policy import opts as policy_opts

from watcher.common import policy as watcher_policy
from watcher.tests import fake_policy

CONF = cfg.CONF


class PolicyFixture(fixtures.Fixture):

    def _setUp(self):
        self.policy_dir = self.useFixture(fixtures.TempDir())
        self.policy_file_name = os.path.join(self.policy_dir.path,
                                             'policy.json')
        with open(self.policy_file_name, 'w') as policy_file:
            policy_file.write(fake_policy.policy_data)
        policy_opts.set_defaults(CONF)
        CONF.set_override('policy_file', self.policy_file_name, 'oslo_policy')
        watcher_policy._ENFORCER = None
        self.addCleanup(watcher_policy.init().clear)

    def set_rules(self, rules):
        policy = watcher_policy._ENFORCER
        policy.set_rules({k: _parser.parse_rule(v)
                          for k, v in rules.items()})
