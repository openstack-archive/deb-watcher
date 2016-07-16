# coding: utf-8
#
# Copyright 2013 Red Hat, Inc.
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

import mock
import webtest
import wsme
from wsme import types as wtypes

from watcher.api.controllers.v1 import types
from watcher.common import exception
from watcher.common import utils
from watcher.tests import base


class TestUuidType(base.TestCase):

    def test_valid_uuid(self):
        test_uuid = '1a1a1a1a-2b2b-3c3c-4d4d-5e5e5e5e5e5e'
        self.assertEqual(test_uuid, types.UuidType.validate(test_uuid))

    def test_invalid_uuid(self):
        self.assertRaises(exception.InvalidUUID,
                          types.UuidType.validate, 'invalid-uuid')


class TestNameType(base.TestCase):

    def test_valid_name(self):
        test_name = 'hal-9000'
        self.assertEqual(test_name, types.NameType.validate(test_name))

    def test_invalid_name(self):
        self.assertRaises(exception.InvalidName,
                          types.NameType.validate, '-this is not valid-')


class TestUuidOrNameType(base.TestCase):

    @mock.patch.object(utils, 'is_uuid_like')
    @mock.patch.object(utils, 'is_hostname_safe')
    def test_valid_uuid(self, host_mock, uuid_mock):
        test_uuid = '1a1a1a1a-2b2b-3c3c-4d4d-5e5e5e5e5e5e'
        host_mock.return_value = False
        uuid_mock.return_value = True
        self.assertTrue(types.UuidOrNameType.validate(test_uuid))
        uuid_mock.assert_called_once_with(test_uuid)

    @mock.patch.object(utils, 'is_uuid_like')
    @mock.patch.object(utils, 'is_hostname_safe')
    def test_valid_name(self, host_mock, uuid_mock):
        test_name = 'dc16-database5'
        uuid_mock.return_value = False
        host_mock.return_value = True
        self.assertTrue(types.UuidOrNameType.validate(test_name))
        host_mock.assert_called_once_with(test_name)

    def test_invalid_uuid_or_name(self):
        self.assertRaises(exception.InvalidUuidOrName,
                          types.UuidOrNameType.validate, 'inval#uuid%or*name')


class MyPatchType(types.JsonPatchType):
    """Helper class for TestJsonPatchType tests."""

    @staticmethod
    def mandatory_attrs():
        return ['/mandatory']

    @staticmethod
    def internal_attrs():
        return ['/internal']


class MyRoot(wsme.WSRoot):
    """Helper class for TestJsonPatchType tests."""

    @wsme.expose([wsme.types.text], body=[MyPatchType])
    @wsme.validate([MyPatchType])
    def test(self, patch):
        return patch


class TestJsonPatchType(base.TestCase):

    def setUp(self):
        super(TestJsonPatchType, self).setUp()
        self.app = webtest.TestApp(MyRoot(['restjson']).wsgiapp())

    def _patch_json(self, params, expect_errors=False):
        return self.app.patch_json(
            '/test',
            params=params,
            headers={'Accept': 'application/json'},
            expect_errors=expect_errors
        )

    def test_valid_patches(self):
        valid_patches = [{'path': '/extra/foo', 'op': 'remove'},
                         {'path': '/extra/foo', 'op': 'add', 'value': 'bar'},
                         {'path': '/str', 'op': 'replace', 'value': 'bar'},
                         {'path': '/bool', 'op': 'add', 'value': True},
                         {'path': '/int', 'op': 'add', 'value': 1},
                         {'path': '/float', 'op': 'add', 'value': 0.123},
                         {'path': '/list', 'op': 'add', 'value': [1, 2]},
                         {'path': '/none', 'op': 'add', 'value': None},
                         {'path': '/empty_dict', 'op': 'add', 'value': {}},
                         {'path': '/empty_list', 'op': 'add', 'value': []},
                         {'path': '/dict', 'op': 'add',
                          'value': {'cat': 'meow'}}]
        ret = self._patch_json(valid_patches, False)
        self.assertEqual(200, ret.status_int)
        self.assertEqual(valid_patches, ret.json)

    def test_cannot_update_internal_attr(self):
        patch = [{'path': '/internal', 'op': 'replace', 'value': 'foo'}]
        ret = self._patch_json(patch, True)
        self.assertEqual(400, ret.status_int)
        self.assertTrue(ret.json['faultstring'])

    def test_cannot_update_internal_dict_attr(self):
        patch = [{'path': '/internal', 'op': 'replace',
                 'value': 'foo'}]
        ret = self._patch_json(patch, True)
        self.assertEqual(400, ret.status_int)
        self.assertTrue(ret.json['faultstring'])

    def test_mandatory_attr(self):
        patch = [{'op': 'replace', 'path': '/mandatory', 'value': 'foo'}]
        ret = self._patch_json(patch, False)
        self.assertEqual(200, ret.status_int)
        self.assertEqual(patch, ret.json)

    def test_cannot_remove_mandatory_attr(self):
        patch = [{'op': 'remove', 'path': '/mandatory'}]
        ret = self._patch_json(patch, True)
        self.assertEqual(400, ret.status_int)
        self.assertTrue(ret.json['faultstring'])

    def test_missing_required_fields_path(self):
        missing_path = [{'op': 'remove'}]
        ret = self._patch_json(missing_path, True)
        self.assertEqual(400, ret.status_int)
        self.assertTrue(ret.json['faultstring'])

    def test_missing_required_fields_op(self):
        missing_op = [{'path': '/foo'}]
        ret = self._patch_json(missing_op, True)
        self.assertEqual(400, ret.status_int)
        self.assertTrue(ret.json['faultstring'])

    def test_invalid_op(self):
        patch = [{'path': '/foo', 'op': 'invalid'}]
        ret = self._patch_json(patch, True)
        self.assertEqual(400, ret.status_int)
        self.assertTrue(ret.json['faultstring'])

    def test_invalid_path(self):
        patch = [{'path': 'invalid-path', 'op': 'remove'}]
        ret = self._patch_json(patch, True)
        self.assertEqual(400, ret.status_int)
        self.assertTrue(ret.json['faultstring'])

    def test_cannot_add_with_no_value(self):
        patch = [{'path': '/extra/foo', 'op': 'add'}]
        ret = self._patch_json(patch, True)
        self.assertEqual(400, ret.status_int)
        self.assertTrue(ret.json['faultstring'])

    def test_cannot_replace_with_no_value(self):
        patch = [{'path': '/foo', 'op': 'replace'}]
        ret = self._patch_json(patch, True)
        self.assertEqual(400, ret.status_int)
        self.assertTrue(ret.json['faultstring'])


class TestBooleanType(base.TestCase):

    def test_valid_true_values(self):
        v = types.BooleanType()
        self.assertTrue(v.validate("true"))
        self.assertTrue(v.validate("TRUE"))
        self.assertTrue(v.validate("True"))
        self.assertTrue(v.validate("t"))
        self.assertTrue(v.validate("1"))
        self.assertTrue(v.validate("y"))
        self.assertTrue(v.validate("yes"))
        self.assertTrue(v.validate("on"))

    def test_valid_false_values(self):
        v = types.BooleanType()
        self.assertFalse(v.validate("false"))
        self.assertFalse(v.validate("FALSE"))
        self.assertFalse(v.validate("False"))
        self.assertFalse(v.validate("f"))
        self.assertFalse(v.validate("0"))
        self.assertFalse(v.validate("n"))
        self.assertFalse(v.validate("no"))
        self.assertFalse(v.validate("off"))

    def test_invalid_value(self):
        v = types.BooleanType()
        self.assertRaises(exception.Invalid, v.validate, "invalid-value")
        self.assertRaises(exception.Invalid, v.validate, "01")


class TestJsonType(base.TestCase):

    def test_valid_values(self):
        vt = types.jsontype
        value = vt.validate("hello")
        self.assertEqual("hello", value)
        value = vt.validate(10)
        self.assertEqual(10, value)
        value = vt.validate(0.123)
        self.assertEqual(0.123, value)
        value = vt.validate(True)
        self.assertTrue(value)
        value = vt.validate([1, 2, 3])
        self.assertEqual([1, 2, 3], value)
        value = vt.validate({'foo': 'bar'})
        self.assertEqual({'foo': 'bar'}, value)
        value = vt.validate(None)
        self.assertIsNone(value)

    def test_invalid_values(self):
        vt = types.jsontype
        self.assertRaises(exception.Invalid, vt.validate, object())

    def test_apimultitype_tostring(self):
        vts = str(types.jsontype)
        self.assertIn(str(wtypes.text), vts)
        self.assertIn(str(int), vts)
        self.assertIn(str(float), vts)
        self.assertIn(str(types.BooleanType), vts)
        self.assertIn(str(list), vts)
        self.assertIn(str(dict), vts)
        self.assertIn(str(None), vts)
