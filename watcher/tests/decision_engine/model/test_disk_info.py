# -*- encoding: utf-8 -*-
# Copyright (c) 2015 b<>com
#
# Authors: Jean-Emile DARTOIS <jean-emile.dartois@b-com.com>
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

from watcher.decision_engine.model import disk_info
from watcher.tests import base


class TestDiskInfo(base.BaseTestCase):
    def test_all(self):
        disk_information = disk_info.DiskInfo()
        disk_information.set_size(1024)
        self.assertEqual(1024, disk_information.get_size())

        disk_information.set_scheduler = "scheduler_qcq"

        disk_information.set_device_name("nom_qcq")
        self.assertEqual("nom_qcq", disk_information.get_device_name())
