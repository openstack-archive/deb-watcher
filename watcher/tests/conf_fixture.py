# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import fixtures
from oslo_config import cfg

from watcher.common import config

CONF = cfg.CONF
CONF.import_opt('host', 'watcher.common.service')
CONF.import_opt('connection', 'oslo_db.options', group='database')
CONF.import_opt('sqlite_synchronous', 'oslo_db.options', group='database')


class ConfFixture(fixtures.Fixture):
    """Fixture to manage conf settings."""

    def __init__(self, conf=cfg.CONF):
        self.conf = conf

    def setUp(self):
        super(ConfFixture, self).setUp()

        self.conf.set_default('connection', "sqlite://", group='database')
        self.conf.set_default('sqlite_synchronous', False, group='database')
        self.conf.set_default('verbose', True)
        config.parse_args([], default_config_files=[])
        self.addCleanup(self.conf.reset)


class ConfReloadFixture(ConfFixture):
    """Fixture to manage reloads of conf settings."""

    def __init__(self, conf=cfg.CONF):
        self.conf = conf
        self._original_parse_cli_opts = self.conf._parse_cli_opts

    def _fake_parser(self, *args, **kw):
        return cfg.ConfigOpts._parse_cli_opts(self.conf, [])

    def _restore_parser(self):
        self.conf._parse_cli_opts = self._original_parse_cli_opts

    def setUp(self):
        super(ConfReloadFixture, self).setUp()
        self.conf._parse_cli_opts = self._fake_parser
        self.addCleanup(self._restore_parser)
